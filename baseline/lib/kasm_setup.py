"""Kasm Workspaces as a Proxmox VM, built on the overlay and persistence design (DR260, DR257/258/259; operator 2026-10-17).

The VM is not permanent; what it holds is. Everything is layers over a vanilla base:

  base       the read-only Debian + Docker + Kasm image in INSTALLER_CACHE (checked against its manifest, never written).
  persisted  an overlay on that base that keeps ALL configuration and data: the OS layer (docker state, anything set in the VM) and the Kasm state on
             APPDATA_ADMIN, the people's profiles on APPDATA_PERSONAL. With these, the VM can be removed ("dehydrated") and built again ("rehydrated") exactly as it was.
  session    only in `reset` mode: a layer on SESSION_TEMP over the persisted one, made fresh at every start, so everything done during a run is discarded and
             the VM comes back as it was when it started. In `persist` mode (the default) there is no session layer and nothing is lost.

  secrets    the four Kasm credentials are generated here and stored in the USER_ADMIN vault BEFORE the guest is told them; nothing is installed with a password
             that is not on record. They reach the guest on stdin through the guest agent, never in a file, a command line or a log.

Every disk is a sparse qcow2 (space is reserved, never written). Existing disks are reused, never replaced. A persisted overlay records the base it was made on and is
not used with a different one. Everything outside Proxmox's own commands goes through the Layout, so tests run in a temp tree.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import kasm_telemetry
import vault as vault_mod

VM_NAME = "baseline-kasm"
BASE_FILE = "kasm-base-1.19.0-debian13.qcow2"
ADMIN_SERIAL, PROFILES_SERIAL = "baseline-kasm-admin", "baseline-kasm-prof"     # 20-character limit on a virtio-blk serial
SECRET_NAMES = ("KASM_ADMIN_PASSWORD", "KASM_USER_PASSWORD", "KASM_DB_PASSWORD", "KASM_MANAGER_TOKEN")
MIN_HOST_MB, MIN_VM_MB, MAX_VM_MB = 12288, 6144, 16384
ADMIN_DISK_GB, PROFILES_DISK_GB = 20, 100
AGENT_WAIT_S, INSTALL_TIMEOUT_S = 300, 1800
GIB = 2**30
# Room asked of each role volume before the VM is built. The disks are sparse, so their size is only a limit; what Kasm actually writes in its first
# minutes (Docker's container layers and sessions, the database and logs, a first profile) must already fit, because the periodic growth check is slower
# than an install. Beyond this the volumes grow as they fill.
ROOM_NEEDED = {"SESSION_TEMP": 8 * GIB, "APPDATA_ADMIN": 12 * GIB, "APPDATA_PERSONAL": 2 * GIB}      # the persisted OS layer is on APPDATA_ADMIN now
MODES = ("persist", "reset")
DEFAULT_MODE = "persist"
LAYOUT = 2            # 1 was the first build: the OS layer was disposable and on SESSION_TEMP. Records without a layout are that one.


class KasmSetupError(Exception):
    """Never carries a secret value."""


class Busy(KasmSetupError):
    """Another Kasm action (a mode change, a removal, a setup) is running."""


@dataclass(frozen=True)
class Layout:
    root_dir: Path = Path("/mnt/SESSION_TEMP/kasm")
    admin_dir: Path = Path("/mnt/APPDATA_ADMIN/kasm")
    profiles_dir: Path = Path("/mnt/APPDATA_PERSONAL/kasm")
    base_dir: Path = Path("/mnt/INSTALLER_CACHE/installer/expanded/baseline-cache/kasm")     # carried with the installer's offline cache
    vault_path: str = vault_mod.ADMIN_VAULT
    pve_conf_dir: Path = Path("/etc/pve/qemu-server")       # where Proxmox keeps a VM's definition (removing it, with the disks left alone, is what "dehydrate" does)
    mounts: tuple = field(default=("/mnt/SESSION_TEMP", "/mnt/APPDATA_ADMIN", "/mnt/APPDATA_PERSONAL", "/mnt/INSTALLER_CACHE", "/mnt/USER_ADMIN"))   # USER_ADMIN holds the vault

    @property
    def base(self) -> Path:
        return self.base_dir / BASE_FILE

    @property
    def record(self) -> Path:
        return self.admin_dir / "vm.json"

    def storages(self):
        """(storage id, path, content) for the three Proxmox directory storages this VM's disks live in."""
        return (("baseline-kasm-root", self.root_dir, "images,iso"), ("baseline-kasm-admin", self.admin_dir, "images"),
                ("baseline-kasm-prof", self.profiles_dir, "images"))


def _run(argv, data=None, timeout=120):
    result = subprocess.run(argv, input=data, capture_output=True, timeout=timeout)
    return result.returncode, result.stdout.decode(errors="replace"), result.stderr.decode(errors="replace")


def host_memory_mb() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) // 1024
    raise KasmSetupError("cannot read the host's memory size")


def size_vm(host_mb: int, host_cores: int) -> dict:
    """Sized from the host, never fixed: a quarter of its memory (6-16 GiB) and half its cores (2-4). Refuses a host too small to share."""
    if host_mb < MIN_HOST_MB:
        raise KasmSetupError(f"this host has {host_mb // 1024} GiB of memory; Kasm needs at least {MIN_VM_MB // 1024} GiB for itself and the host needs the rest")
    return {"memory_mb": min(MAX_VM_MB, max(MIN_VM_MB, host_mb // 4)), "cpus": min(4, max(2, host_cores // 2))}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class KasmSetup:
    def __init__(self, layout: Layout = Layout(), *, run=_run, is_mount=os.path.ismount, sleep=time.sleep, hash_file=file_sha256,
                 vault=None, host_mb=None, host_cores=None, clock=time.monotonic, ensure_room=None):
        self.layout, self.run, self.is_mount, self.sleep, self.hash_file, self.clock = layout, run, is_mount, sleep, hash_file, clock
        self.vault = vault if vault is not None else vault_mod.Vault(layout.vault_path)
        self._host_mb, self._host_cores = host_mb, host_cores
        self.ensure_room = ensure_room      # callable(label, needed_bytes) that extends a Baseline role volume; None where volumes do not grow

    @contextlib.contextmanager
    def _exclusive(self):
        """One action at a time: the timer that keeps the VM running must not start it while a mode change or a removal has it stopped on purpose."""
        self.layout.admin_dir.mkdir(parents=True, exist_ok=True)
        handle = open(self.layout.admin_dir / ".action.lock", "a")
        try:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Busy("another Kasm action is running; try again when it has finished") from None
            yield
        finally:
            handle.close()

    # ---- Proxmox -----------------------------------------------------------------------------------------------------
    def _command(self, argv, **kwargs):
        rc, out, err = self.run(argv, **kwargs) if kwargs else self.run(argv)
        if rc:
            raise KasmSetupError(f"{argv[0]} {argv[1]} failed: {err.strip()[-300:]}")
        return out

    def _json(self, argv):
        try:
            return json.loads(self._command(argv))
        except ValueError as exc:
            raise KasmSetupError(f"{argv[0]} returned something that is not JSON") from exc

    def existing_vmid(self):
        """The VMID Proxmox already has for this VM, or None. More than one VM with the name is refused rather than guessed at."""
        found = [r for r in self._json(["pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"]) if r.get("name") == VM_NAME]
        if len(found) > 1:
            raise KasmSetupError(f"more than one VM is named {VM_NAME}; refusing to guess which is Kasm")
        return found[0]["vmid"] if found else None

    def read_record(self) -> dict:
        try:
            record = json.loads(self.layout.record.read_text())
        except (OSError, ValueError):
            return {}
        return record if isinstance(record, dict) else {}

    def recorded_vmid(self):
        """The VMID the admin disk was built under (a rebuild must reuse it: the persistent disks sit under that number)."""
        vmid = self.read_record().get("vmid")
        return vmid if isinstance(vmid, int) and not isinstance(vmid, bool) and 100 <= vmid <= 999999999 else None

    def _ensure_storages(self):
        definitions = self._json(["pvesh", "get", "/storage", "--output-format", "json"])
        for ident, path, content in self.layout.storages():
            existing = next((d for d in definitions if d.get("storage") == ident), None)
            if existing is not None:
                if existing.get("type") != "dir" or Path(existing.get("path", "")).resolve() != path.resolve():
                    raise KasmSetupError(f"storage {ident} already exists with a different type or path")
                continue
            path.mkdir(parents=True, exist_ok=True)
            mount = Path("/mnt") / path.resolve().parts[2] if path.resolve().is_relative_to("/mnt") else None
            self._command(["pvesm", "add", "dir", ident, "--path", str(path), "--content", content] + (["--is_mountpoint", str(mount)] if mount else []))

    # ---- checks ------------------------------------------------------------------------------------------------------
    def check_base(self) -> dict:
        """The base is vanilla and read-only: verified against its manifest each time, never written."""
        manifest_path = self.layout.base_dir / "KASM.json"
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError) as exc:
            raise KasmSetupError(f"the Kasm base's manifest is missing or unreadable at {manifest_path}") from exc
        if not self.layout.base.is_file():
            raise KasmSetupError(f"the Kasm base image is not in the installer cache ({self.layout.base})")
        if manifest.get("holds_install_state_or_secrets") is not False:
            raise KasmSetupError("the Kasm base's manifest does not say it is free of install state and secrets; refusing to use it")
        if self.hash_file(self.layout.base) != manifest.get("sha256"):
            raise KasmSetupError("the Kasm base image does not match its manifest checksum; refusing to boot it")
        return manifest

    def make_room(self):
        """Ask each role volume the VM writes to for what its first minutes need. A volume that cannot provide it stops the build with the reason."""
        if self.ensure_room is None:
            return
        for label, needed in ROOM_NEEDED.items():
            try:
                self.ensure_room(label, needed)
            except Exception as exc:        # noqa: BLE001 - the growth module's own reason is what the person needs to read
                raise KasmSetupError(f"{label} cannot be given the room Kasm needs: {exc}") from exc

    def check_volumes(self):
        missing = [m for m in self.layout.mounts if not self.is_mount(m)]
        if missing:
            raise KasmSetupError(f"these volumes must be mounted first: {', '.join(missing)}")

    def sizing(self) -> dict:
        return size_vm(self._host_mb if self._host_mb is not None else host_memory_mb(), self._host_cores or os.cpu_count() or 2)

    # ---- disks -------------------------------------------------------------------------------------------------------
    @staticmethod
    def disk_name(vmid, index):
        return f"vm-{vmid}-disk-{index}.qcow2"

    def _disk_path(self, directory: Path, vmid, index) -> Path:
        return directory / "images" / str(vmid) / self.disk_name(vmid, index)

    def persisted_path(self, vmid, index) -> Path:
        """0 the OS layer and 1 Kasm's state (APPDATA_ADMIN), 2 the profiles (APPDATA_PERSONAL)."""
        return self._disk_path(self.layout.profiles_dir if index == 2 else self.layout.admin_dir, vmid, index)

    def session_path(self, vmid, index) -> Path:
        return self._disk_path(self.layout.root_dir, vmid, index)

    def _make_disk(self, path: Path, options: list, size: str = ""):
        """Created only when absent; an existing disk is the user's data and is never replaced or resized here. Always a bare sparse qcow2."""
        if path.is_symlink():
            raise KasmSetupError(f"{path} is a link; refusing to use it")
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        self._command(["qemu-img", "create", "-q", "-f", "qcow2", *options, str(path), *([size] if size else [])])
        return True

    def create_persisted(self, vmid, admin_gb=ADMIN_DISK_GB, profiles_gb=PROFILES_DISK_GB):
        """The layers that keep everything, each only if absent."""
        self._make_disk(self.persisted_path(vmid, 0), ["-b", str(self.layout.base), "-F", "qcow2"])
        self._make_disk(self.persisted_path(vmid, 1), [], f"{int(admin_gb)}G")
        self._make_disk(self.persisted_path(vmid, 2), [], f"{int(profiles_gb)}G")

    def fresh_session_layer(self, vmid):
        """A new, empty layer over each persisted disk (reset mode); whatever an earlier run wrote is gone."""
        for index in range(3):
            self.drop_session_disk(vmid, index)
            path = self.session_path(vmid, index)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._command(["qemu-img", "create", "-q", "-f", "qcow2", "-b", str(self.persisted_path(vmid, index)), "-F", "qcow2", str(path)])

    def drop_session_disk(self, vmid, index):
        path = self.session_path(vmid, index)
        if path.is_symlink():
            raise KasmSetupError(f"{path} is a link; refusing to remove it")
        path.unlink(missing_ok=True)

    def drop_session_layer(self, vmid):
        for index in range(3):
            self.drop_session_disk(vmid, index)

    def disk_arguments(self, vmid, mode) -> list:
        """The `--virtioN` attachments for a mode: the persisted disks themselves, or the session layer over them. Data disks keep their serials."""
        store = {0: "baseline-kasm-admin", 1: "baseline-kasm-admin", 2: "baseline-kasm-prof"}
        out = []
        for index in range(3):
            volume = f"{'baseline-kasm-root' if mode == 'reset' else store[index]}:{vmid}/{self.disk_name(vmid, index)}"
            serial = {1: f",serial={ADMIN_SERIAL}", 2: f",serial={PROFILES_SERIAL}"}.get(index, "")
            out += [f"--virtio{index}", volume + serial]
        return out

    def make_seed(self, vmid) -> str:
        """The cloud-init seed: names the machine and turns password sign-in off. It holds no secret. Returns the Proxmox volume id."""
        iso_dir = self.layout.root_dir / "template" / "iso"
        iso_dir.mkdir(parents=True, exist_ok=True)
        target = iso_dir / f"{VM_NAME}-seed.iso"
        src = self.layout.root_dir / "seed"
        src.mkdir(parents=True, exist_ok=True)
        (src / "user-data").write_text("#cloud-config\nssh_pwauth: false\ndisable_root: true\n")
        (src / "meta-data").write_text(f"instance-id: {VM_NAME}-{vmid}\nlocal-hostname: kasm\n")
        self._command(["xorriso", "-as", "mkisofs", "-quiet", "-V", "cidata", "-J", "-r", "-o", str(target), str(src)])
        shutil.rmtree(src, ignore_errors=True)
        return f"baseline-kasm-root:iso/{target.name}"

    # ---- the VM ------------------------------------------------------------------------------------------------------
    def create_vm(self, vmid, size, seed_volume, mode=DEFAULT_MODE, mac=None):
        net = "virtio" + (f"={mac}" if mac else "") + ",bridge=vmbr0"
        self._command(["qm", "create", str(vmid), "--name", VM_NAME, "--memory", str(size["memory_mb"]), "--cores", str(size["cpus"]),
                       "--machine", "q35", "--cpu", "host", "--ostype", "l26", "--net0", net, "--agent", "enabled=1",
                       "--serial0", "socket", "--vga", "serial0", "--onboot", "1", *self.disk_arguments(vmid, mode),
                       "--ide2", f"{seed_volume},media=cdrom", "--boot", "order=virtio0"])

    def start_vm(self, vmid, record=None):
        """Starts the VM. In reset mode the session layer is made fresh first, so the VM begins from the persisted state, never from a past run's changes."""
        record = self.read_record() if record is None else record
        if record.get("layout") == LAYOUT and record.get("mode") == "reset":
            if self.vm_status(vmid) == "running":
                raise KasmSetupError("the VM is running; a reset-mode start needs it stopped first")
            self.fresh_session_layer(vmid)
        self._command(["qm", "start", str(vmid)])

    def wait_for_agent(self, vmid, timeout=AGENT_WAIT_S):
        end = self.clock() + timeout
        while self.clock() < end:
            rc, _out, _err = self.run(["qm", "agent", str(vmid), "ping"])
            if rc == 0:
                return
            self.sleep(5)
        raise KasmSetupError("the Kasm VM's guest agent did not answer in time")

    def vm_status(self, vmid) -> str:
        out = self._command(["qm", "status", str(vmid)]).strip()
        if out not in ("status: running", "status: stopped"):
            raise KasmSetupError(f"unexpected Proxmox status: {out}")
        return out.split(": ")[1]

    def address(self, vmid):
        """https address of Kasm from the guest agent's own view of its network; None until the guest has one."""
        rc, out, _err = self.run(["qm", "agent", str(vmid), "network-get-interfaces"])
        if rc:
            return None
        try:
            interfaces = json.loads(out)
        except ValueError:
            return None
        for interface in interfaces if isinstance(interfaces, list) else []:
            for item in interface.get("ip-addresses", []):
                ip = item.get("ip-address", "")
                if item.get("ip-address-type") == "ipv4" and not ip.startswith(("127.", "169.254.")):
                    return f"https://{ip}"
        return None

    # ---- credentials -------------------------------------------------------------------------------------------------
    def credentials(self, passphrase=None) -> dict:
        """The four credentials, from the vault when it already has them (a rebuild must use the ones the database was made with), otherwise
        new and stored first. A vault that cannot be written is a refusal: nothing is installed with a password that is not on record."""
        have = {}
        for name in SECRET_NAMES:
            try:
                value = self.vault.get(name, passphrase=passphrase)
            except vault_mod.VaultError as exc:
                raise KasmSetupError(f"the credential vault cannot be read ({type(exc).__name__}); unlock it first") from None
            if value:
                have[name] = value
        if len(have) not in (0, len(SECRET_NAMES)):
            raise KasmSetupError("the vault holds some but not all of the Kasm credentials; refusing to guess which are right")
        if have:
            return have
        fresh = {name: secrets.token_hex(16) for name in SECRET_NAMES}
        try:
            for name, value in fresh.items():
                self.vault.put(name, value, passphrase=passphrase)
        except vault_mod.VaultError:
            raise KasmSetupError("the credential vault cannot be written (is it unlocked?); nothing is installed without a recorded password") from None
        return fresh

    DOCKER_DROPIN = "/etc/systemd/system/docker.service.d/baseline-kasm-install.conf"

    def _guest_shell(self, vmid, script, timeout=120):
        """True only when the command ran in the guest AND exited 0 (`qm guest exec` itself succeeds whatever the command's own exit code is)."""
        rc, out, _err = self.run(["qm", "guest", "exec", str(vmid), "--synchronous", "1", "--timeout", str(timeout), "--", "/bin/bash", "-c", script],
                                 timeout=timeout + 30)
        try:
            result = json.loads(out)
        except (ValueError, TypeError):
            return False
        return rc == 0 and isinstance(result, dict) and result.get("exitcode") == 0 and not result.get("signal")

    def _guest_output(self, vmid, script, timeout=120):
        """What a read-only command printed inside the guest, or None when it could not run or did not exit 0."""
        rc, out, _err = self.run(["qm", "guest", "exec", str(vmid), "--synchronous", "1", "--timeout", str(timeout), "--", "/bin/bash", "-c", script], timeout=timeout + 30)
        try:
            result = json.loads(out)
        except (ValueError, TypeError):
            return None
        if rc or not isinstance(result, dict) or result.get("exitcode") != 0 or result.get("signal"):
            return None
        return str(result.get("out-data", ""))

    def telemetry_db(self):
        self.layout.admin_dir.mkdir(parents=True, exist_ok=True)
        return kasm_telemetry.open_db(self.layout.admin_dir / "telemetry.sqlite")

    def collect_telemetry(self, now=None) -> dict:
        """Ask the running VM how it is doing and keep the answer. Quiet when there is nothing to ask (no VM, not running, no agent)."""
        vmid = self.existing_vmid()
        if vmid is None or self.vm_status(vmid) != "running":
            return {"collected": False, "reason": "the Kasm VM is not running"}
        out = self._guest_output(vmid, kasm_telemetry.PROBE)
        if out is None:
            return {"collected": False, "reason": "the VM did not answer the probe"}
        metrics, events = kasm_telemetry.parse_probe(out)
        now = time.time() if now is None else now
        conn = self.telemetry_db()
        try:
            kasm_telemetry.record(conn, metrics, events, now=now)
            kasm_telemetry.prune(conn, now - 30 * kasm_telemetry.DAY)
        finally:
            conn.close()
        return {"collected": True, "metrics": len(metrics), "events": len(events)}

    def telemetry_report(self, now=None) -> dict:
        """What the history says to change, why, and what it buys, plus the repeating errors and the settings changed, with their values."""
        record = self.read_record()
        now = time.time() if now is None else now
        vm = {"memory_mb": record.get("memory_mb") or 0, "cpus": record.get("cpus") or 0}
        conn = self.telemetry_db()
        try:
            since = now - 7 * kasm_telemetry.DAY
            return {"suggestions": kasm_telemetry.suggestions(conn, vm, now=now) if vm["memory_mb"] and vm["cpus"] else [],
                    "errors": kasm_telemetry.error_report(conn, since), "setting_changes": kasm_telemetry.setting_report(conn, now - 90 * kasm_telemetry.DAY),
                    "launches": kasm_telemetry.launches_report(conn, now - 30 * kasm_telemetry.DAY)}
        finally:
            conn.close()

    def run_install(self, vmid, creds):
        """Kasm's installer restarts Docker several times in a row; on a slow host that trips systemd's start-rate limit ("start of the service was attempted too
        often") and the install stops half-way (found on a nested Proxmox, 2026-10-17). So the limit is lifted for the install and put back afterwards.
        The data disks are brought up first, too: after a rebuild the guest agent answers before the VM's own start-up has mounted them, and the installer's
        "already installed?" check would look at an unmounted folder (found the same day)."""
        if not self._guest_shell(vmid, "/usr/local/sbin/baseline-kasm-disks"):
            raise KasmSetupError("the VM's data disks could not be brought up; nothing was installed")
        self._guest_shell(vmid, f"mkdir -p {os.path.dirname(self.DOCKER_DROPIN)} && printf '[Unit]\\nStartLimitIntervalSec=0\\n' > {self.DOCKER_DROPIN} && "
                                "systemctl daemon-reload && systemctl reset-failed docker.service docker.socket || true")
        try:
            data = "".join(f"{name}={creds[name]}\n" for name in SECRET_NAMES)
            registry = (self.carried_recipe() or {}).get("registry") or {}
            if registry.get("enabled") and registry.get("list_url"):
                data += f"KASM_REGISTRY_URL={registry['list_url']}\n"            # not a secret: where Kasm finds workspaces (Baseline's own registry)
            data = data.encode()
            rc, out, _err = self.run(["qm", "guest", "exec", str(vmid), "--pass-stdin", "1", "--synchronous", "1", "--timeout", str(INSTALL_TIMEOUT_S),
                                      "--", "/usr/local/sbin/baseline-kasm-install"], data=data, timeout=INSTALL_TIMEOUT_S + 60)
        finally:
            self._guest_shell(vmid, f"rm -f {self.DOCKER_DROPIN}; systemctl daemon-reload")
        try:
            result = json.loads(out)
        except (ValueError, TypeError):
            result = {}
        if rc or not isinstance(result, dict) or result.get("exitcode") != 0 or result.get("signal"):
            # the installer's own log (in the VM) holds the reason; it also holds Kasm's generated tokens, so none of it is quoted here
            raise KasmSetupError("the Kasm install did not finish successfully; the reason is in /var/log/kasm-install.log inside the VM")

    # ---- the whole thing ---------------------------------------------------------------------------------------------
    def setup(self, *, passphrase=None, admin_gb=ADMIN_DISK_GB, profiles_gb=PROFILES_DISK_GB) -> dict:
        try:
            with self._exclusive():
                return self._setup(passphrase=passphrase, admin_gb=admin_gb, profiles_gb=profiles_gb)
        except Busy:
            return {"busy": True}                     # the timer's call: another action has the VM in hand; nothing is done and nothing is wrong

    def set_mode(self, mode) -> dict:
        with self._exclusive():
            return self._set_mode(mode)

    def dehydrate(self) -> dict:
        with self._exclusive():
            return self._dehydrate()

    def reset_root(self, confirm=False) -> dict:
        with self._exclusive():
            return self._reset_root(confirm=confirm)

    def _write_record(self, **updates) -> dict:
        record = {**self.read_record(), **updates}
        self.layout.record.parent.mkdir(parents=True, exist_ok=True)
        self.layout.record.write_text(json.dumps(record, indent=1))
        return record

    def _setup(self, *, passphrase=None, admin_gb=ADMIN_DISK_GB, profiles_gb=PROFILES_DISK_GB) -> dict:
        """Idempotent. A VM that is there and installed is only made sure of (cheap: no base check, no guest work). A VM that is gone (dehydrated, or lost) is
        built again from its persisted layers under the same VMID, memory, cores and address, in the mode it had."""
        vmid = self.existing_vmid()
        record = self.read_record()
        if vmid is not None and record.get("vmid") == vmid and record.get("installed"):
            if self.vm_status(vmid) != "running":
                self.start_vm(vmid, record)
            return {**record, "created": False, "url": self.address(vmid)}
        self.check_volumes()
        manifest = self.check_base()
        legacy = bool(record) and record.get("layout") != LAYOUT
        if not legacy and record.get("base_sha256") and record["base_sha256"] != manifest.get("sha256") and self.persisted_path(record.get("vmid", 0), 0).exists():
            raise KasmSetupError("the persisted layers were made on a different Kasm base than the one carried now; they are not used with it")
        size = {k: record[k] for k in ("memory_mb", "cpus") if record.get(k)} if record.get("memory_mb") else self.sizing()
        self._ensure_storages()
        self.make_room()
        mode = record.get("mode", DEFAULT_MODE) if not legacy else DEFAULT_MODE
        created = vmid is None
        if created:
            vmid = self.recorded_vmid() or int(self._command(["pvesh", "get", "/cluster/nextid"]).strip())
            self.create_persisted(vmid, admin_gb, profiles_gb)
            if mode == "reset":
                self.fresh_session_layer(vmid)
            self.create_vm(vmid, size, self.make_seed(vmid), mode, mac=(record.get("definition") or {}).get("mac"))
        if self.vm_status(vmid) != "running":
            self._command(["qm", "start", str(vmid)])
        self.wait_for_agent(vmid)
        creds = self.credentials(passphrase)
        self.run_install(vmid, creds)               # a no-op in the guest when it is already installed
        state = self._write_record(vmid=vmid, kasm_version=manifest.get("kasm_version"), base_sha256=manifest.get("sha256"), installed=True,
                                   layout=LAYOUT, mode=mode, dehydrated=False, **size)
        return {**state, "created": created, "url": self.address(vmid)}

    def carried_workspaces(self):
        """The workspaces the carried base says it holds (its manifest), or None when there is no readable manifest."""
        try:
            rows = json.loads((self.layout.base_dir / "KASM.json").read_text()).get("workspaces")
        except (OSError, ValueError):
            return None
        return rows if isinstance(rows, list) else None

    def carried_recipe(self):
        """The recipe summary the carried base's manifest records (its components and whether anything offered uses them), or None."""
        try:
            recipe = json.loads((self.layout.base_dir / "KASM.json").read_text()).get("recipe")
        except (OSError, ValueError):
            return None
        return recipe if isinstance(recipe, dict) and isinstance(recipe.get("components"), list) else None

    def status(self) -> dict:
        """What is there now, without changing anything."""
        vmid = self.existing_vmid()
        record = self.read_record()
        mode = record.get("mode", DEFAULT_MODE) if record.get("layout") == LAYOUT else None
        if vmid is None:
            return {"present": False, "installed": bool(record.get("installed")), "dehydrated": bool(record.get("dehydrated")), "mode": mode,
                    "recorded_vmid": self.recorded_vmid(), "workspaces": self.carried_workspaces(), "recipe": self.carried_recipe()}
        running = self.vm_status(vmid) == "running"
        return {"present": True, "vmid": vmid, "running": running, "installed": bool(record.get("installed")), "mode": mode,
                "dehydrated": False, "url": self.address(vmid) if running else None, "memory_mb": record.get("memory_mb"), "cpus": record.get("cpus"),
                "workspaces": self.carried_workspaces(), "recipe": self.carried_recipe()}

    def _stopped(self, vmid):
        if self.vm_status(vmid) != "stopped":
            self._command(["qm", "shutdown", str(vmid), "--timeout", "180", "--forceStop", "1"])
        if self.vm_status(vmid) != "stopped":
            raise KasmSetupError("the VM did not stop")

    def _set_mode(self, mode) -> dict:
        """persist: everything done is kept. reset: everything done during a run is discarded and the VM starts from where it was. Needs a restart of the VM."""
        if mode not in MODES:
            raise KasmSetupError(f"the run mode is one of: {', '.join(MODES)}")
        vmid = self.existing_vmid()
        record = self.read_record()
        if vmid is None:
            raise KasmSetupError("there is no Kasm VM; set it up first")
        if record.get("layout") != LAYOUT:
            raise KasmSetupError("this VM was built with the first layout, which has no run modes; remove it and set it up again to use them")
        self.check_volumes()
        self._stopped(vmid)
        for index in range(3):                                   # the layers the VM is attached to
            self.drop_session_disk(vmid, index)
        if mode == "reset":
            self.fresh_session_layer(vmid)
        arguments = self.disk_arguments(vmid, mode)
        self._command(["qm", "set", str(vmid), *arguments])
        if mode == "persist":
            self.drop_session_layer(vmid)
        self._write_record(mode=mode)
        self._command(["qm", "start", str(vmid)])
        self.wait_for_agent(vmid)
        return {"vmid": vmid, "mode": mode, "url": self.address(vmid)}

    def _dehydrate(self) -> dict:
        """Remove the VM and keep everything it held: its definition is recorded, its persisted layers stay where they are, and `setup` builds it again exactly as it was.
        The VM must be stopped (it is shut down first). Only this module's own VM is touched, by its recorded id and name."""
        vmid = self.existing_vmid()
        record = self.read_record()
        if vmid is None:
            raise KasmSetupError("there is no Kasm VM to remove")
        if record.get("layout") != LAYOUT or record.get("vmid") != vmid:
            raise KasmSetupError("this VM was not built with the persisted layers, so removing it would lose its OS layer; not removed")
        conf = Path(self.layout.pve_conf_dir) / f"{vmid}.conf"
        if conf.is_symlink() or not conf.is_file():
            raise KasmSetupError("the VM's definition is not where Proxmox keeps it; not removed")
        self._stopped(vmid)
        text = self._command(["qm", "config", str(vmid)])
        fields = dict(line.split(": ", 1) for line in text.splitlines() if ": " in line)
        if fields.get("name") != VM_NAME or "lock" in fields:
            raise KasmSetupError("the VM's name or lock is not what this module made; not removed")
        mac = next((part.split("=", 1)[1] for part in fields.get("net0", "").split(",") if part.startswith("virtio=")), None)
        for index in range(3):
            if not self.persisted_path(vmid, index).is_file():
                raise KasmSetupError("a persisted layer is missing; removing the VM would lose more than its definition; not removed")
        self._write_record(dehydrated=True, definition={"mac": mac, "memory": fields.get("memory"), "cores": fields.get("cores")})
        conf.unlink()                                            # the VM's definition only; Proxmox is left holding no reference to the disks
        self.drop_session_layer(vmid)
        if self.existing_vmid() is not None:
            raise KasmSetupError("Proxmox still lists the VM after its definition was removed")
        return {"vmid": vmid, "dehydrated": True, "kept": [str(self.persisted_path(vmid, i)) for i in range(3)]}

    def _reset_root(self, confirm=False) -> dict:
        """Throw the OS layer away and boot a new one over the same base; Kasm's state and the profiles are not touched. This DISCARDS the persisted OS layer, so it
        needs `confirm` (the run mode `reset` is the way to discard a run's changes without losing the OS layer)."""
        if not confirm:
            raise KasmSetupError("this discards the persisted OS layer; it needs explicit confirmation")
        vmid = self.existing_vmid()
        if vmid is None:
            raise KasmSetupError("there is no Kasm VM to reset")
        self.check_volumes()
        self.check_base()
        record = self.read_record()
        self._stopped(vmid)
        persisted = self.persisted_path(vmid, 0) if record.get("layout") == LAYOUT else self.session_path(vmid, 0)
        if persisted.is_symlink():
            raise KasmSetupError("the root disk is a link; refusing to replace it")
        persisted.unlink(missing_ok=True)
        self._make_disk(persisted, ["-b", str(self.layout.base), "-F", "qcow2"])
        self.start_vm(vmid, record)
        self.wait_for_agent(vmid)
        return {"vmid": vmid, "url": self.address(vmid)}
