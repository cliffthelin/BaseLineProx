#!/usr/bin/env python3
"""Host-network repair - Layer 1 of the BaselineOS repair plane
(docs/design/reset-interface-to-dhcp-plan.md, v2/v3). The first bounded
action: `reset_interface_to_dhcp`.

AI/Baseline boundary: the harness (harness.py::propose_repair) may name a
candidate `target_interface` and its reasoning, but nothing here trusts
that proposal. `plan_repair()` re-derives the real target itself from
observed state (topology.derive_target), and every precondition, the
backup, the write, the reload, and the verification are Baseline's own
code - the model never executes anything.

Everything that shells out, touches the filesystem, or reads the clock
goes through a `Runner` (see below), so the whole pipeline is unit-testable
with no real `ip`/`ifreload`/`systemd-run` invocation and no real file
outside a temp directory - see tests/test_repair.py.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import ifnet_config  # noqa: E402
import network  # noqa: E402
import topology  # noqa: E402

INTERFACES_PATH = "/etc/network/interfaces"
REPAIR_STATE_DIR = Path("/var/lib/baseline/repair")
PENDING_MANIFEST_PATH = REPAIR_STATE_DIR / "pending" / "manifest.json"
EVENT_LOG = network.EVENT_LOG  # same JSONL file network.py already writes to

DEFAULT_ROLLBACK_WINDOW_S = 120
DEFAULT_AUTH_TIMEOUT_S = 300
BACKUP_RETENTION_MIN_ATTEMPTS = 10
BACKUP_RETENTION_MIN_DAYS = 30
# SSH's own default plus whatever's actually configured, and Proxmox's web/
# API port - never "every TCP connection" (v1's mistake, corrected per
# Cliff's review). Extra ports are operator-configurable via
# /etc/baseline/protected_ports.json (see load_protected_ports below).
DEFAULT_PROTECTED_PORTS = {22, 8006}

GATEWAY_PROBE_TIMEOUT_S = 3.0
STABILIZATION_DELAY_S = 5


# --------------------------------------------------------------------------
# Runner: the injectable subprocess/filesystem/clock boundary. Every
# production call goes through RealRunner; every test uses a FakeRunner
# (see tests/) that records calls and returns scripted results. No other
# function in this module calls subprocess/open/time directly.
# --------------------------------------------------------------------------

class Runner:
    def run(self, argv, timeout=10):
        raise NotImplementedError

    def read_text(self, path):
        raise NotImplementedError

    def write_text_atomic(self, path, content):
        """Write `content` to `path` atomically (temp file + fsync +
        os.replace), preserving the existing file's mode/owner if it
        already exists."""
        raise NotImplementedError

    def append_text(self, path, content):
        raise NotImplementedError

    def path_exists(self, path):
        raise NotImplementedError

    def remove(self, path):
        raise NotImplementedError

    def makedirs(self, path):
        raise NotImplementedError

    def listdir(self, path):
        raise NotImplementedError

    def now(self):
        raise NotImplementedError

    def sleep(self, seconds):
        raise NotImplementedError


class RealRunner(Runner):
    def run(self, argv, timeout=10):
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return subprocess.CompletedProcess(argv, 127, "", str(exc))

    def read_text(self, path):
        return Path(path).read_text()

    def write_text_atomic(self, path, content):
        path = Path(path)
        tmp = path.with_suffix(path.suffix + f".tmp-baseline-{os.getpid()}")
        mode, uid, gid = 0o644, None, None
        if path.exists():
            st = path.stat()
            mode, uid, gid = st.st_mode, st.st_uid, st.st_gid
        tmp.write_text(content)
        os.chmod(tmp, mode)
        if uid is not None:
            try:
                os.chown(tmp, uid, gid)
            except (PermissionError, OSError):
                pass
        with open(tmp, "r+") as f:
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def append_text(self, path, content):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(content)

    def path_exists(self, path):
        return Path(path).exists()

    def remove(self, path):
        p = Path(path)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)

    def makedirs(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)

    def listdir(self, path):
        p = Path(path)
        return sorted(p.iterdir()) if p.exists() else []

    def now(self):
        return time.time()

    def sleep(self, seconds):
        time.sleep(seconds)


# --------------------------------------------------------------------------
# Refusal
# --------------------------------------------------------------------------

class RepairRefused(Exception):
    """Raised by any precondition/guard. `code` is a stable, machine-
    readable reason (tested against directly); `detail` is the
    operator-facing explanation; `candidates` carries ambiguous-topology
    choices when relevant."""

    def __init__(self, code: str, detail: str, candidates=None):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.candidates = candidates or []


@dataclass
class RepairResult:
    ok: bool
    attempt_id: str
    outcome: str  # "success" | "refused" | "declined" | "rolled_back" | "rollback_failed"
    detail: str = ""
    events: list = field(default_factory=list)


# --------------------------------------------------------------------------
# Event logging - same file network.py writes to, component="repair".
# --------------------------------------------------------------------------

def log_event(runner: Runner, attempt_id: str, step: str, status: str, detail: str = "", **extra):
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(runner.now())),
        "component": "repair",
        "attempt_id": attempt_id,
        "step": step,
        "status": status,
        "detail": detail,
    }
    rec.update(extra)
    runner.append_text(str(EVENT_LOG), json.dumps(rec) + "\n")
    return rec


# --------------------------------------------------------------------------
# ifupdown2 capability detection - detected, never assumed; no fallback to
# ifdown/ifup on failure (Cliff's explicit instruction).
# --------------------------------------------------------------------------

@dataclass
class Ifupdown2Capability:
    present: bool
    ifreload_path: str = ""
    version: str = ""
    detail: str = ""


def detect_ifupdown2(runner: Runner) -> Ifupdown2Capability:
    which = runner.run(["which", "ifreload"])
    if which.returncode != 0 or not which.stdout.strip():
        return Ifupdown2Capability(False, detail="ifreload not found on PATH")
    ifreload_path = which.stdout.strip().splitlines()[0]

    pkg = runner.run(["dpkg-query", "-W", "-f=${Version}", "ifupdown2"])
    if pkg.returncode != 0:
        return Ifupdown2Capability(False, ifreload_path=ifreload_path,
                                    detail="ifreload is present but the ifupdown2 package is not - "
                                           "refusing rather than guessing this is the real thing")
    version = pkg.stdout.strip()
    return Ifupdown2Capability(True, ifreload_path=ifreload_path, version=version)


# --------------------------------------------------------------------------
# Cluster safety - this action is for a standalone host only. Any evidence
# of cluster membership refuses the action outright, action-wide - a plain
# TCP connection check cannot adequately protect Corosync or the rest of a
# cluster's non-TCP dependencies, and multi-node Proxmox is out of scope.
# --------------------------------------------------------------------------

def check_standalone_host(runner: Runner) -> None:
    for path in ("/etc/pve/corosync.conf", "/etc/corosync/corosync.conf"):
        if runner.path_exists(path):
            raise RepairRefused("cluster_member",
                                 f"{path} exists - this host appears to belong to a Proxmox cluster; "
                                 "host-network repair is scoped to a standalone host only")
    pvecm = runner.run(["pvecm", "status"], timeout=5)
    if pvecm.returncode == 0 and pvecm.stdout.strip():
        raise RepairRefused("cluster_member",
                             "`pvecm status` succeeded - this host reports cluster membership; "
                             "host-network repair is scoped to a standalone host only")


# --------------------------------------------------------------------------
# Connection guard - protects specific management paths (SSH, Proxmox's
# API port, configured ports, the current remote session if identifiable),
# not every TCP connection. Never infers "the operator's" session by
# guessing among sockets (Cliff's explicit instruction) - any live session
# on a protected port is protected, full stop.
# --------------------------------------------------------------------------

def load_protected_ports(runner: Runner) -> set:
    ports = set(DEFAULT_PROTECTED_PORTS)
    path = "/etc/baseline/protected_ports.json"
    if runner.path_exists(path):
        try:
            extra = json.loads(runner.read_text(path))
            ports |= {int(p) for p in extra}
        except (ValueError, TypeError):
            pass
    return ports


@dataclass
class ProtectedSession:
    local_port: int
    peer: str


def find_protected_sessions(runner: Runner, physical_devices: list, protected_ports: set) -> list:
    """Live TCP sessions on a protected port, best-effort scoped to the
    devices under the target interface via `ss -tnp`'s interface hint
    where available; if `ss` can't scope by device, protected-port
    sessions are treated as protected regardless of device, which is the
    conservative direction to be wrong in."""
    result = runner.run(["ss", "-tn", "state", "established"])
    if result.returncode != 0:
        # Can't determine live sessions at all - fail safe: assume
        # something might be protected rather than assume nothing is.
        return [ProtectedSession(-1, "unknown (ss unavailable)")]
    sessions = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3]
        try:
            local_port = int(local.rsplit(":", 1)[-1])
        except ValueError:
            continue
        if local_port in protected_ports:
            peer = parts[4] if len(parts) > 4 else "?"
            sessions.append(ProtectedSession(local_port, peer))
    return sessions


def check_connection_guard(runner: Runner, physical_devices: list, operator_present: bool) -> list:
    """Returns the list of protected sessions found (possibly empty).
    Raises RepairRefused only when execution would be unattended - an
    operator physically present at tty1 (operator_present=True, set only
    by the TUI's own local confirmation flow, never settable remotely) may
    proceed after being shown this same list."""
    ports = load_protected_ports(runner)
    sessions = find_protected_sessions(runner, physical_devices, ports)
    if sessions and not operator_present:
        raise RepairRefused("protected_connection_unattended",
                             f"{len(sessions)} protected management session(s) found "
                             f"(ports: {sorted({s.local_port for s in sessions})}) and no operator is "
                             "physically present at tty1 to authorize the disruption; refusing unattended "
                             "execution - a remote session may never authorize severing its own access path",
                             candidates=sessions)
    return sessions


# --------------------------------------------------------------------------
# Reading and hashing the interfaces config closure
# --------------------------------------------------------------------------

def read_interfaces_config(runner: Runner, root_path: str = INTERFACES_PATH) -> ifnet_config.ParsedConfig:
    """Resolve `source`/`source-directory` recursively and hand every file
    read to ifnet_config.parse_files - I/O lives here, parsing stays
    pure.

    A glob-form `source <pattern>` target (e.g.
    "source /etc/network/interfaces.d/*" - confirmed, Milestone 1 Phase
    0, to be exactly what Proxmox's automated installer generates) is
    resolved here via Runner.listdir + ifnet_config.resolve_source_glob,
    the same directory-listing mechanism `source-directory` already
    uses, rather than being treated as a literal (and un-openable) file
    path. Before this fix, a glob-shaped `source` target would raise
    OSError on the literal string and be silently recorded as an empty
    file - which could hide real fragment files instead of reading them.
    An empty or missing directory resolves to zero matches, which is the
    normal, expected case for a fresh install and is not an error.
    """
    files = {}
    to_read = [root_path]
    seen = set()
    while to_read:
        path = to_read.pop(0)
        if path in seen:
            continue
        seen.add(path)
        try:
            text = runner.read_text(path)
        except OSError as exc:
            files[path] = ""
            continue
        files[path] = text
        for line in text.splitlines():
            m = ifnet_config.SOURCE_RE.match(line)
            if m:
                target = m.group(1)
                if ifnet_config._has_glob_metachars(target):
                    parent = target.rsplit("/", 1)[0] or "/"
                    try:
                        entries = [str(e) for e in runner.listdir(parent)]
                    except OSError:
                        entries = []
                    to_read.extend(ifnet_config.resolve_source_glob(target, entries))
                else:
                    to_read.append(target)
                continue
            m = ifnet_config.SOURCE_DIR_RE.match(line)
            if m:
                for entry in runner.listdir(m.group(1)):
                    to_read.append(str(entry))
    return ifnet_config.parse_files(files)


# --------------------------------------------------------------------------
# Backup management
# --------------------------------------------------------------------------

def _attempt_dir(attempt_id: str) -> Path:
    return REPAIR_STATE_DIR / attempt_id


def create_backup(runner: Runner, attempt_id: str, cfg: ifnet_config.ParsedConfig) -> dict:
    """Write every file in the config closure into the attempt's backup
    directory, then read each one back and byte-compare - an unverified
    backup blocks the action (RepairRefused), never silently proceeds."""
    adir = _attempt_dir(attempt_id)
    runner.makedirs(str(adir / "backup"))
    manifest = {}
    for path, text in cfg.files.items():
        backup_path = adir / "backup" / path.lstrip("/").replace("/", "__")
        runner.write_text_atomic(str(backup_path), text)
        readback = runner.read_text(str(backup_path))
        if readback != text:
            raise RepairRefused("backup_unverified",
                                 f"backup of {path} did not read back identically - refusing to proceed")
        manifest[path] = {"backup_path": str(backup_path), "hash": ifnet_config.hash_text(text)}
    closure_hash = ifnet_config.hash_closure(cfg.files)
    runner.write_text_atomic(str(adir / "backup_manifest.json"),
                              json.dumps({"files": manifest, "closure_hash": closure_hash,
                                          "created_at": runner.now()}))
    return {"closure_hash": closure_hash, "files": manifest}


def restore_backup(runner: Runner, attempt_id: str) -> tuple:
    """Restore every backed-up file verbatim. Returns
    (config_restoration_confirmed: bool, detail: str)."""
    adir = _attempt_dir(attempt_id)
    manifest_path = adir / "backup_manifest.json"
    if not runner.path_exists(str(manifest_path)):
        return False, f"no backup manifest found for attempt {attempt_id}"
    manifest = json.loads(runner.read_text(str(manifest_path)))
    for path, info in manifest["files"].items():
        original = runner.read_text(info["backup_path"])
        if ifnet_config.hash_text(original) != info["hash"]:
            return False, f"backup for {path} failed its own hash check - not restoring from a corrupt backup"
        runner.write_text_atomic(path, original)
        readback = runner.read_text(path)
        if ifnet_config.hash_text(readback) != info["hash"]:
            return False, f"restore of {path} did not read back identically"
    return True, "all backed-up files restored and hash-verified"


def prune_old_backups(runner: Runner) -> None:
    """Retention: keep at least the last 10 attempts or 30 days, whichever
    preserves more. Never removes an attempt directory whose manifest is
    missing an explicit 'closed' marker (i.e. an incomplete/failed repair
    is never pruned - see close_attempt below)."""
    if not runner.path_exists(str(REPAIR_STATE_DIR)):
        return
    entries = []
    for d in runner.listdir(str(REPAIR_STATE_DIR)):
        d = Path(d)
        if d.name == "pending" or not runner.path_exists(str(d / "backup_manifest.json")):
            continue
        manifest_path = d / "attempt_status.json"
        closed_at = None
        if runner.path_exists(str(manifest_path)):
            try:
                status = json.loads(runner.read_text(str(manifest_path)))
                closed_at = status.get("closed_at")
            except ValueError:
                closed_at = None
        entries.append((d, closed_at))
    # Only ever consider closed attempts for pruning.
    closed = sorted([(d, ts) for d, ts in entries if ts is not None], key=lambda x: x[1], reverse=True)
    now = runner.now()
    keep = set()
    for i, (d, ts) in enumerate(closed):
        if i < BACKUP_RETENTION_MIN_ATTEMPTS or (now - ts) < BACKUP_RETENTION_MIN_DAYS * 86400:
            keep.add(d)
    for d, ts in closed:
        if d not in keep:
            runner.remove(str(d))


def close_attempt(runner: Runner, attempt_id: str, outcome: str) -> None:
    adir = _attempt_dir(attempt_id)
    runner.write_text_atomic(str(adir / "attempt_status.json"),
                              json.dumps({"outcome": outcome, "closed_at": runner.now()}))
    prune_old_backups(runner)


# --------------------------------------------------------------------------
# Pending manifest - the narrow, restore-only contract a same-boot rollback
# (and, once its systemd ordering is verified, the permanent boot-time
# recovery service) consumes independently of the main Baseline process.
# See docs/design/reset-interface-to-dhcp-plan.md's "Open items": the
# permanent dormant service itself is NOT installed by this change - see
# repair_rollback.py's module docstring for why.
# --------------------------------------------------------------------------

def write_pending_manifest(runner: Runner, attempt_id: str, target_interface: str, rollback_unit: str) -> None:
    runner.makedirs(str(PENDING_MANIFEST_PATH.parent))
    runner.write_text_atomic(str(PENDING_MANIFEST_PATH), json.dumps({
        "attempt_id": attempt_id,
        "target_interface": target_interface,
        "rollback_unit": rollback_unit,
        "created_at": runner.now(),
    }))


def read_pending_manifest(runner: Runner):
    if not runner.path_exists(str(PENDING_MANIFEST_PATH)):
        return None
    return json.loads(runner.read_text(str(PENDING_MANIFEST_PATH)))


def clear_pending_manifest(runner: Runner) -> None:
    if runner.path_exists(str(PENDING_MANIFEST_PATH)):
        runner.remove(str(PENDING_MANIFEST_PATH))


# --------------------------------------------------------------------------
# Independent rollback arming - a genuinely transient systemd timer
# (systemd-run, never written to /etc/systemd/system) for the ordinary
# same-boot window. Survives Baseline/TUI/repair-worker crashing (systemd,
# not this process, holds the timer); does NOT survive a reboot - that gap
# is exactly the permanent-service piece this change holds back pending
# real systemd-ordering verification (see repair_rollback.py).
# --------------------------------------------------------------------------

def rollback_unit_name(attempt_id: str) -> str:
    return f"baseline-repair-rollback-{attempt_id}"


def arm_rollback(runner: Runner, attempt_id: str, window_s: int) -> str:
    unit = rollback_unit_name(attempt_id)
    result = runner.run([
        "systemd-run", f"--unit={unit}", "--collect",
        f"--on-active={window_s}",
        "/opt/baseline/bin/baseline-repair-rollback", "same-boot", attempt_id,
    ], timeout=10)
    if result.returncode != 0:
        raise RepairRefused("rollback_arm_failed",
                             f"could not arm the independent rollback timer: {result.stderr.strip()}")
    return unit


def cancel_rollback(runner: Runner, unit: str) -> bool:
    result = runner.run(["systemctl", "stop", f"{unit}.timer"], timeout=10)
    return result.returncode == 0


# --------------------------------------------------------------------------
# Target-bound verification - proves the repaired interface itself is
# healthy, never substitutes network.py's global check_lifeline() for
# this (a live USB tether or second NIC could otherwise mask a still-
# broken target).
# --------------------------------------------------------------------------

@dataclass
class VerificationResult:
    ok: bool
    address: str = ""
    gateway: str = ""
    detail: str = ""


def verify_target(runner: Runner, target_interface: str, stabilize: bool = True) -> VerificationResult:
    addr_res = runner.run(["ip", "-4", "-o", "addr", "show", "dev", target_interface], timeout=5)
    address = ""
    for line in addr_res.stdout.splitlines():
        parts = line.split()
        if "inet" in parts:
            address = parts[parts.index("inet") + 1].split("/")[0]
    if not address:
        return VerificationResult(False, detail=f"{target_interface} has no IPv4 address")

    route_res = runner.run(["ip", "-4", "route", "show", "dev", target_interface], timeout=5)
    gateway = ""
    for line in route_res.stdout.splitlines():
        if line.startswith("default via"):
            gateway = line.split()[2]
    if not gateway:
        return VerificationResult(False, address=address,
                                   detail=f"{target_interface} has an address but no default route via it")

    ping = runner.run(["ping", "-c", "1", "-W", str(int(GATEWAY_PROBE_TIMEOUT_S)),
                        "-I", target_interface, gateway], timeout=int(GATEWAY_PROBE_TIMEOUT_S) + 2)
    if ping.returncode != 0:
        return VerificationResult(False, address=address, gateway=gateway,
                                   detail=f"gateway {gateway} not reachable through {target_interface} itself")

    if stabilize:
        runner.sleep(STABILIZATION_DELAY_S)
        again = verify_target(runner, target_interface, stabilize=False)
        if not again.ok:
            return VerificationResult(False, address=address, gateway=gateway,
                                       detail=f"reachable once, then failed the stabilization re-check: {again.detail}")
    return VerificationResult(True, address=address, gateway=gateway, detail="verified through the target interface itself")


# --------------------------------------------------------------------------
# The bounded action itself - the transactional pipeline, exactly in the
# order Cliff specified:
#   1 discover topology
#   2 validate candidate
#   3 create and byte-verify backup
#   4 arm independent rollback   <- before any write
#   5 write candidate atomically
#   6 validate syntax (without applying)
#   7 apply
#   8 verify lifeline (target-bound)
#   9 cancel rollback only on success
# --------------------------------------------------------------------------

def plan_repair(runner: Runner, observed_dev: str, proposed_target: str = "") -> topology.DerivationResult:
    """Steps 1-2, read-only: derive the real target and validate it's a
    legitimate candidate. Never trusts `proposed_target` - only compares
    against it for logging."""
    cfg = read_interfaces_config(runner)
    result = topology.derive_target(observed_dev, cfg)
    if proposed_target and result.ok and proposed_target != result.target.name:
        # Logged by the caller as a discrepancy - derivation still wins.
        pass
    return result


def reset_interface_to_dhcp(runner: Runner, observed_dev: str, requested_by: str,
                             proposed_target: str = "", operator_present: bool = False,
                             rollback_window_s: int = DEFAULT_ROLLBACK_WINDOW_S,
                             check_lifeline_fn=None) -> RepairResult:
    """`check_lifeline_fn` defaults to network.py's real, non-injectable
    `check_lifeline()` (it talks to real sockets/subprocess directly, by
    design - it's the same deterministic check the rest of Baseline
    trusts). Tests pass a fake in its place so this pipeline never
    actually probes a real network."""
    check_lifeline_fn = check_lifeline_fn or network.check_lifeline
    attempt_id = str(uuid.uuid4())
    log_event(runner, attempt_id, "proposed", "info",
              f"observed_dev={observed_dev} proposed_target={proposed_target!r} requested_by={requested_by}")

    try:
        # --- 1: discover topology / 2: validate candidate ---
        check_standalone_host(runner)

        cap = detect_ifupdown2(runner)
        if not cap.present:
            raise RepairRefused("unsupported_environment", cap.detail)

        derivation = plan_repair(runner, observed_dev, proposed_target)
        if not derivation.ok:
            raise RepairRefused("topology_ambiguous" if len(derivation.candidates) > 1 else "no_static_config",
                                 derivation.reason, candidates=derivation.candidates)
        target = derivation.target
        if proposed_target and proposed_target != target.name:
            log_event(runner, attempt_id, "target_discrepancy", "info",
                      f"harness proposed {proposed_target!r}, Baseline derived {target.name!r} - using the derivation")

        facts = check_lifeline_fn()
        fact_map = {f["fact"]: f for f in facts}
        gw_fact = fact_map.get("gateway_reachable")
        addr_fact = fact_map.get("address_assigned")
        if (gw_fact is None or gw_fact["ok"]) and (addr_fact is None or addr_fact["ok"]):
            raise RepairRefused("already_healthy",
                                 f"{target.name} currently reports address_assigned/gateway_reachable OK - "
                                 "refusing to change a device that isn't actually broken")

        sessions = check_connection_guard(runner, target.physical_devices, operator_present)
        if sessions:
            log_event(runner, attempt_id, "protected_sessions_disclosed", "info",
                      f"{len(sessions)} protected session(s), operator present, proceeding with disclosure",
                      protected_ports=sorted({s.local_port for s in sessions}))

        log_event(runner, attempt_id, "validated", "info", f"target_interface={target.name}",
                  target_interface=target.name, topology=target.kind)

        # --- 3: create and byte-verify backup ---
        cfg = read_interfaces_config(runner)
        backup = create_backup(runner, attempt_id, cfg)
        log_event(runner, attempt_id, "backup_written", "info", "backup byte-verified",
                  backup_hash=backup["closure_hash"])

        # --- 4: arm independent rollback, before any write ---
        unit = arm_rollback(runner, attempt_id, rollback_window_s)
        write_pending_manifest(runner, attempt_id, target.name, unit)
        log_event(runner, attempt_id, "rollback_armed", "info", f"unit={unit} window={rollback_window_s}s",
                  rollback_unit=unit)

        # --- revalidate immediately before writing: closure must be unchanged ---
        cfg_now = read_interfaces_config(runner)
        if ifnet_config.hash_closure(cfg_now.files) != backup["closure_hash"]:
            cancel_rollback(runner, unit)
            clear_pending_manifest(runner)
            close_attempt(runner, attempt_id, "refused_concurrent_change")
            raise RepairRefused("concurrent_config_change",
                                 "interfaces config changed since the backup was taken - refusing to overwrite "
                                 "a change this action didn't make or review; a fresh proposal is needed")

        # --- 5: write candidate atomically ---
        try:
            new_files = ifnet_config.rewrite_stanza_to_dhcp(cfg_now, target.name)
        except ifnet_config.RewriteError as exc:
            restored, restore_detail = restore_backup(runner, attempt_id)
            cancel_rollback(runner, unit)
            clear_pending_manifest(runner)
            close_attempt(runner, attempt_id, "refused_rewrite_error")
            raise RepairRefused("rewrite_error", f"{exc}; restore: {restore_detail}")

        for path, text in new_files.items():
            if text != cfg_now.files[path]:
                runner.write_text_atomic(path, text)
        log_event(runner, attempt_id, "written", "info", f"{target.name} rewritten to inet dhcp")

        # --- 6: validate syntax without applying ---
        check = runner.run(["ifreload", "--syntax-check", "-a"], timeout=15)
        if check.returncode != 0:
            restored, restore_detail = restore_backup(runner, attempt_id)
            cancel_rollback(runner, unit)
            clear_pending_manifest(runner)
            close_attempt(runner, attempt_id, "refused_syntax_invalid")
            log_event(runner, attempt_id, "restored", "info" if restored else "fail", restore_detail)
            raise RepairRefused("syntax_invalid",
                                 f"ifreload --syntax-check failed: {check.stderr.strip()}; restore: {restore_detail}")

        # --- 7: apply ---
        apply_res = runner.run(["ifreload", "-a"], timeout=30)
        log_event(runner, attempt_id, "applied", "pass" if apply_res.returncode == 0 else "fail",
                  apply_res.stderr.strip() if apply_res.returncode else "ifreload -a completed")
        if apply_res.returncode != 0:
            # Leave the independent rollback armed per spec - do not race
            # it with an inline restore.
            raise RepairRefused("apply_failed", f"ifreload -a failed: {apply_res.stderr.strip()}; "
                                                 "independent rollback stays armed")

        # --- 8: verify lifeline, target-bound ---
        verification = verify_target(runner, target.name)
        if not verification.ok:
            log_event(runner, attempt_id, "verify_timeout", "fail", verification.detail)
            # Leave rollback armed; it fires on its own.
            return RepairResult(False, attempt_id, "rolled_back",
                                 f"target-bound verification failed ({verification.detail}); "
                                 "independent rollback remains armed and will restore the original config")

        log_event(runner, attempt_id, "verify_pass", "pass",
                  f"address={verification.address} gateway={verification.gateway}")

        # --- 9: cancel rollback only on success ---
        cancel_rollback(runner, unit)
        clear_pending_manifest(runner)
        close_attempt(runner, attempt_id, "success")
        log_event(runner, attempt_id, "cancelled_rollback", "info", "verification succeeded")
        return RepairResult(True, attempt_id, "success",
                             f"{target.name} reset to DHCP; address={verification.address} "
                             f"gateway={verification.gateway}")

    except RepairRefused as refusal:
        log_event(runner, attempt_id, "refused", "fail", refusal.detail, code=refusal.code)
        return RepairResult(False, attempt_id, "refused", f"{refusal.code}: {refusal.detail}")
