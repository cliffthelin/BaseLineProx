"""App-specific LXC/VM provisioning via community-scripts/ProxmoxVE's
Helper-Scripts - resolves decision record 35's explicitly deferred
"LXC app-installer vendoring... needs a concrete first target" item,
picking two of the exact candidates that record itself named
(Pi-hole, Home Assistant OS), plus a few more (see
docs/design/decision-records/57-vm-scripts-pinned-community-helper-scripts.md).

**Relationship to `pct_provision.py`/`vm_provision.py` - read before
assuming this builds on them, because it doesn't.** Those two modules
are Baseline-native, Runner-tested, minimal `pct create`/`qm create`
primitives with no opinion about what runs inside the guest. This
module is a different, parallel path: it fetches and runs an
upstream Helper-Script that calls `pct create`/`qm create` *itself*,
internally, with upstream's own opinionated defaults - Baseline never
sees or controls that inner command. Picking `debian-lxc` here does
**not** go through `pct_provision.create_ct`. That's a real
architectural seam, not an oversight - unifying them (e.g. having this
module shell out through `pct_provision.py` instead of upstream's own
script logic) is real, separate follow-up work, not assumed solved
here.

Community-maintained, MIT-licensed, one-command LXC/VM installers
already exist for hundreds of services - reusing them for the
app-specific cases is the correct call over hand-porting each one's
install logic into `pct_provision.py`/`vm_provision.py`. But upstream's
own recommended invocation is a blind `bash -c "$(curl -fsSL <url>)"`
against a moving `main` branch ref - exactly the "remote-fetch and pipe
straight to bash" pattern this project's own security instincts reject
everywhere else (the same instinct that rejected a full
`xdg-desktop-portal` trust boundary in milestone-2-gui-plan.md).

This module closes that gap for the part that's actually closeable:

1. Every script Baseline can run is pinned to one immutable upstream
   commit (raw.githubusercontent.com content at a commit SHA never
   changes, unlike `main`, which moves).
2. Its content is sha256-verified against a manifest entry computed
   directly from that pinned commit before this module ever existed -
   never invented, never trusted from an unverified source.
3. An unknown script_id, a fetch failure, or a hash mismatch all refuse
   outright, before a single byte reaches bash - matching
   settings_web.py's "unknown section is refused, never guessed at"
   discipline.

**Known, disclosed limitation - read before relying on this for
anything you consider fully sandboxed:** the entry-point script
(`ct/*.sh`/`vm/*.sh`) sources a second file, `core/build.func` (a
separate repo, `community-scripts/core`), which this module also pins
and verifies (`CORE_PINNED_COMMIT`/`CORE_BUILD_FUNC_SHA256`) and
supplies locally via the `COMMUNITY_SCRIPTS_CORE_DIR` override hook
upstream itself already exposes for exactly this purpose - so neither
of those two hops runs unverified content.

`core/build.func` itself, however, contains a generic
`_cs_download`/`_cs_remote_url`-driven mechanism that can source
*further* remote files at runtime, whose exact set depends on
control flow (which app/OS is being installed) that this module does
not statically enumerate. **That transitive fetch path is not pinned
or verified by this module today.** This is the same "clone detection
isn't solvable in the general case" honesty testpersistence-prd
applies to itself (see its S:5's scoped claim) - don't claim more
closure here than actually exists.

**A real QEMU smoke test (decision record 59) found something more
concrete and more important than that theoretical gap: `run_script()`
does NOT fail safely on a non-Proxmox host.** Run against a plain
Debian VM with no `pct`/`qm` present at all, `ct/debian.sh` did not
error out - it silently took its own "already-installed, update in
place" branch instead (these Helper-Scripts are dual-purpose: create
*and* update the same container) and ran a real `apt` update/upgrade
directly on the host in ~8 seconds, reporting `outcome: applied`,
`returncode: 0`. **Never assume a missing Proxmox environment makes
this module inert - it can mutate whatever real host it's run
against, Proxmox or not.** Treat `run_script()` as
operator-supervised-only (never wired to any automatic/scheduled
trigger, never invoked by the harness on its own initiative) until a
fully vendored, network-isolated execution environment closes this
properly - matching the OpenHands lesson that agent-adjacent code
execution belongs in a sandbox, not directly on the host, once true
autonomy is ever considered here.
"""
from __future__ import annotations

import hashlib
import json
import shlex
import time
from dataclasses import dataclass
from pathlib import Path

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:  # minimal shape match for standalone use/testing
        def run(self, argv, timeout=10):
            raise NotImplementedError

        def write_text_atomic(self, path, content):
            raise NotImplementedError

        def append_text(self, path, content):
            raise NotImplementedError


UPSTREAM_SCRIPTS_REPO = "community-scripts/ProxmoxVE"
UPSTREAM_CORE_REPO = "community-scripts/core"

# Pinned 2026-09-27 from each repo's real `main` HEAD at verification time -
# immutable (a commit SHA's raw content never changes, unlike `main`
# itself). Re-pin deliberately: fetch the new commit, recompute every
# sha256 below by hand, update both together - never silently track
# `main`. See decision record 57 for the exact steps taken.
PINNED_COMMIT = "e2effe6510ff2ece1aa1cb71863ef2e92709f39e"
CORE_PINNED_COMMIT = "cbf119ed58df13cd74450faec727a70052a35f1c"
CORE_BUILD_FUNC_SHA256 = "95c08ed1aab000e375f52eb5a4a82ade180d35e75082d58424484fc8208f3cc4"

# Where the verified core/build.func is staged locally so the pinned
# entry-point script sources *this* copy instead of live-fetching `main`
# (COMMUNITY_SCRIPTS_CORE_DIR is upstream's own override hook for exactly
# this - see build.func's own _cs_boot line).
CORE_STATE_DIR = "/var/lib/baseline/vm_scripts/core-verified"
CORE_BUILD_FUNC_PATH = f"{CORE_STATE_DIR}/core/build.func"

EVENT_LOG = "/var/log/baseline/vm_scripts.events.jsonl"


@dataclass(frozen=True)
class ScriptInfo:
    script_id: str
    path: str  # e.g. "ct/docker.sh", relative to UPSTREAM_SCRIPTS_REPO
    kind: str  # "lxc" | "vm"
    description: str
    sha256: str  # verified directly from PINNED_COMMIT's raw content


# Curated subset only - deliberately not all 600+ upstream scripts. Each
# sha256 was computed directly from PINNED_COMMIT's raw content before
# being added here. Extending this list means re-doing that
# verification for the new entry, not just adding a path.
SCRIPT_MANIFEST: dict[str, ScriptInfo] = {
    "debian-lxc": ScriptInfo(
        "debian-lxc", "ct/debian.sh", "lxc",
        "Plain Debian LXC container - the generic base case",
        "5fdc82ef42d8b0c692dc655c07f0e172222e856d8632a9ddf05bdcfc188c6dcb"),
    "docker-lxc": ScriptInfo(
        "docker-lxc", "ct/docker.sh", "lxc",
        "Debian LXC with Docker pre-installed",
        "c606f9f46d08162416010d3d76e6e12c0fd5d18cc2b4429841b298559bc65a83"),
    "homeassistant-lxc": ScriptInfo(
        "homeassistant-lxc", "ct/homeassistant.sh", "lxc",
        "Home Assistant Core in an LXC container",
        "7fe0134aafdd2645288d20b806c6b8e1dd4694096663da612dd8d3c8d22efce5"),
    "pihole-lxc": ScriptInfo(
        "pihole-lxc", "ct/pihole.sh", "lxc",
        "Pi-hole DNS ad-blocker LXC container",
        "eb689b3382917dac957a9775ee51d4bda616abb47c6f189674e7ade908fe0beb"),
    "debian-vm": ScriptInfo(
        "debian-vm", "vm/debian-vm.sh", "vm",
        "Plain Debian VM - the generic base case for a full VM",
        "2caa2558d1d1f23e0013cfc01ff9dce98a46c9456c6530e5cdd620122fa4bfa9"),
    "haos-vm": ScriptInfo(
        "haos-vm", "vm/haos-vm.sh", "vm",
        "Home Assistant OS VM",
        "9eae079a801edcf92906053a88bba10b0bacd56b9966c506abeee21a62cce7fc"),
}


def list_scripts() -> list[ScriptInfo]:
    """Pure - no I/O. The curated known-good catalog, never upstream's
    live (and much larger, unvetted) list."""
    return sorted(SCRIPT_MANIFEST.values(), key=lambda s: s.script_id)


def raw_url(path: str, *, repo: str, commit: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"


@dataclass
class FetchResult:
    ok: bool
    content: str | None
    error: str | None


def _fetch(runner: Runner, *, repo: str, commit: str, path: str) -> FetchResult:
    proc = runner.run(["curl", "-fsSL", raw_url(path, repo=repo, commit=commit)], timeout=20)
    if proc.returncode != 0:
        return FetchResult(False, None, f"fetch failed (curl exit {proc.returncode}): {proc.stderr.strip()[:200]}")
    return FetchResult(True, proc.stdout, None)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class VerifiedScript:
    outcome: str  # "applied" | "refused"
    content: str | None
    detail: str


def verify_and_get(runner: Runner, script_id: str) -> VerifiedScript:
    """Fetch + hash-verify the entry-point script only, never execute.
    `content` is populated only when outcome == "applied" - every
    refusal path leaves it None so a caller can never mistake a
    refused result's content for something safe to run."""
    script = SCRIPT_MANIFEST.get(script_id)
    if script is None:
        return VerifiedScript(
            "refused", None,
            f"{script_id!r} is not on the known-script allow-list; known ids: {sorted(SCRIPT_MANIFEST)}")

    fetched = _fetch(runner, repo=UPSTREAM_SCRIPTS_REPO, commit=PINNED_COMMIT, path=script.path)
    if not fetched.ok:
        return VerifiedScript("refused", None, fetched.error)

    actual = _sha256(fetched.content)
    if actual != script.sha256:
        return VerifiedScript(
            "refused", None,
            f"sha256 mismatch for {script_id!r} at pinned commit {PINNED_COMMIT[:12]} - "
            f"expected {script.sha256}, got {actual}. Refusing to run unverified content; "
            f"upstream may have rewritten history, or this is tampering in transit. "
            f"Re-verify by hand before re-pinning - never widen this check to accept it.")
    return VerifiedScript("applied", fetched.content,
                           f"{script_id!r} verified against pinned commit {PINNED_COMMIT[:12]}")


def verify_core_build_func(runner: Runner) -> VerifiedScript:
    """Same discipline, for the one named transitive dependency
    upstream's own override hook lets us pin (see module docstring for
    what this does and does NOT close)."""
    fetched = _fetch(runner, repo=UPSTREAM_CORE_REPO, commit=CORE_PINNED_COMMIT, path="core/build.func")
    if not fetched.ok:
        return VerifiedScript("refused", None, fetched.error)
    actual = _sha256(fetched.content)
    if actual != CORE_BUILD_FUNC_SHA256:
        return VerifiedScript(
            "refused", None,
            f"sha256 mismatch for core/build.func at pinned commit {CORE_PINNED_COMMIT[:12]} - "
            f"expected {CORE_BUILD_FUNC_SHA256}, got {actual}. Refusing to stage it.")
    return VerifiedScript("applied", fetched.content, "core/build.func verified")


def _log_event(runner: Runner, event: dict) -> None:
    event = {"ts": time.time(), **event}
    try:
        runner.append_text(EVENT_LOG, json.dumps(event) + "\n")
    except Exception:
        pass  # logging must never be why a real operation fails or succeeds


@dataclass
class RunOutcome:
    outcome: str  # "applied" | "refused"
    detail: str


DEFAULT_EXECUTION_TIMEOUT_S = 1800


def run_script(runner: Runner, script_id: str, *, timeout: int = DEFAULT_EXECUTION_TIMEOUT_S) -> RunOutcome:
    """Verify the entry-point script AND core/build.func, stage the
    verified build.func locally, then execute - the one place this
    module actually creates a VM/LXC (the Helper-Script itself calls
    `pct create`/`qm create` internally, exactly as upstream intends).
    Every attempt - refused or applied - is durably logged, so a
    repeated failed/refused attempt is exactly the kind of
    count-preserving signal tools/bounded_log.py's discipline is meant
    to feed, not silent noise.

    Never wire this to an automatic/scheduled trigger or let the
    harness invoke it on its own initiative - see the module docstring's
    disclosed limitation on core/build.func's own further transitive
    fetches. This is an explicit, human-invoked action only."""
    verified = verify_and_get(runner, script_id)
    if verified.outcome != "applied":
        _log_event(runner, {"script_id": script_id, "outcome": "refused", "stage": "entry_script", "detail": verified.detail})
        return RunOutcome("refused", verified.detail)

    core = verify_core_build_func(runner)
    if core.outcome != "applied":
        _log_event(runner, {"script_id": script_id, "outcome": "refused", "stage": "core_build_func", "detail": core.detail})
        return RunOutcome("refused", f"core/build.func verification failed: {core.detail}")

    runner.write_text_atomic(CORE_BUILD_FUNC_PATH, core.content)

    prelude = f"export COMMUNITY_SCRIPTS_CORE_DIR={shlex.quote(CORE_STATE_DIR)}\n"
    proc = runner.run(["bash", "-c", prelude + verified.content], timeout=timeout)
    outcome = "applied" if proc.returncode == 0 else "refused"
    detail = (proc.stdout.strip()[-2000:] if outcome == "applied"
              else f"script exited {proc.returncode}: {proc.stderr.strip()[-2000:]}")
    _log_event(runner, {"script_id": script_id, "outcome": outcome, "stage": "execute", "detail": detail[:500]})
    return RunOutcome(outcome, detail)
