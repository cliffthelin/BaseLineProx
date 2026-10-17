"""Kasm Workspaces as a Proxmox VM, built on the overlay-and-persistence design (DR260, DR257/258/259).

What goes where (the disks are attached by serial, so the guest never depends on device letters):
  root     overlay on SESSION_TEMP whose backing file is the vanilla base in INSTALLER_CACHE (read only: checked, never written). Disposable:
           a rebuilt or reset OS is a new overlay over the same base.
  admin    APPDATA_ADMIN: Kasm's own state (configuration, certificates, keys, logs, the Postgres data).
  profiles APPDATA_PERSONAL: the browser/desktop profiles people keep, mounted by Kasm at /mnt/kasm_profiles/{user_id}/{image_id}.
  secrets  the four Kasm credentials are generated here and stored in the USER_ADMIN vault BEFORE the guest is told them; nothing is installed
           with a password that is not on record. They reach the guest on stdin through the guest agent, never in a file, a command line or a log.

Every disk is a sparse qcow2 (space is reserved, never written). Existing disks are reused, never replaced: a rebuild finds the admin and profile
disks under the same VMID and attaches them again. Everything outside Proxmox's own commands goes through the Layout, so tests run in a temp tree.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

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
ROOM_NEEDED = {"SESSION_TEMP": 8 * GIB, "APPDATA_ADMIN": 4 * GIB, "APPDATA_PERSONAL": 2 * GIB}


class KasmSetupError(Exception):
    """Never carries a secret value."""


@dataclass(frozen=True)
class Layout:
    root_dir: Path = Path("/mnt/SESSION_TEMP/kasm")
    admin_dir: Path = Path("/mnt/APPDATA_ADMIN/kasm")
    profiles_dir: Path = Path("/mnt/APPDATA_PERSONAL/kasm")
    base_dir: Path = Path("/mnt/INSTALLER_CACHE/installer/expanded/baseline-cache/kasm")     # carried with the installer's offline cache
    vault_path: str = vault_mod.ADMIN_VAULT
    mounts: tuple = field(default=("/mnt/SESSION_TEMP", "/mnt/APPDATA_ADMIN", "/mnt/APPDATA_PERSONAL", "/mnt/INSTALLER_CACHE"))

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

    def _make_disk(self, path: Path, options: list, size: str = ""):
        """Created only when absent; an existing disk is the user's data and is never replaced or resized here. Always a bare sparse qcow2."""
        if path.is_symlink():
            raise KasmSetupError(f"{path} is a link; refusing to use it")
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        self._command(["qemu-img", "create", "-q", "-f", "qcow2", *options, str(path), *([size] if size else [])])
        return True

    def create_root(self, vmid) -> Path:
        path = self._disk_path(self.layout.root_dir, vmid, 0)
        self._make_disk(path, ["-b", str(self.layout.base), "-F", "qcow2"])
        return path

    def create_data_disks(self, vmid, admin_gb=ADMIN_DISK_GB, profiles_gb=PROFILES_DISK_GB):
        self._make_disk(self._disk_path(self.layout.admin_dir, vmid, 1), [], f"{int(admin_gb)}G")
        self._make_disk(self._disk_path(self.layout.profiles_dir, vmid, 2), [], f"{int(profiles_gb)}G")

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
    def create_vm(self, vmid, size, seed_volume):
        self._command(["qm", "create", str(vmid), "--name", VM_NAME, "--memory", str(size["memory_mb"]), "--cores", str(size["cpus"]),
                       "--machine", "q35", "--cpu", "host", "--ostype", "l26", "--net0", "virtio,bridge=vmbr0", "--agent", "enabled=1",
                       "--serial0", "socket", "--vga", "serial0", "--onboot", "1",
                       "--virtio0", f"baseline-kasm-root:{vmid}/{self.disk_name(vmid, 0)}",
                       "--virtio1", f"baseline-kasm-admin:{vmid}/{self.disk_name(vmid, 1)},serial={ADMIN_SERIAL}",
                       "--virtio2", f"baseline-kasm-prof:{vmid}/{self.disk_name(vmid, 2)},serial={PROFILES_SERIAL}",
                       "--ide2", f"{seed_volume},media=cdrom", "--boot", "order=virtio0"])

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

    def run_install(self, vmid, creds):
        data = "".join(f"{name}={creds[name]}\n" for name in SECRET_NAMES).encode()
        rc, out, _err = self.run(["qm", "guest", "exec", str(vmid), "--pass-stdin", "1", "--synchronous", "1", "--timeout", str(INSTALL_TIMEOUT_S),
                                  "--", "/usr/local/sbin/baseline-kasm-install"], data=data, timeout=INSTALL_TIMEOUT_S + 60)
        try:
            result = json.loads(out)
        except (ValueError, TypeError):
            result = {}
        if rc or not isinstance(result, dict) or result.get("exitcode") != 0 or result.get("signal"):
            tail = str(result.get("out-data", "") if isinstance(result, dict) else "")[-300:]
            raise KasmSetupError(f"the Kasm install did not finish successfully{(': ' + tail) if tail else ''}")

    # ---- the whole thing ---------------------------------------------------------------------------------------------
    def setup(self, *, passphrase=None, admin_gb=ADMIN_DISK_GB, profiles_gb=PROFILES_DISK_GB) -> dict:
        """Idempotent: a VM that is already there and installed is only made sure of (cheap: no base check, no guest work); a rebuild after the VM
        was destroyed reattaches the persistent disks under their old VMID."""
        vmid = self.existing_vmid()
        record = self.read_record()
        if vmid is not None and record.get("vmid") == vmid and record.get("installed"):
            if self.vm_status(vmid) != "running":
                self._command(["qm", "start", str(vmid)])
            return {**record, "created": False, "url": self.address(vmid)}
        self.check_volumes()
        manifest = self.check_base()
        size = self.sizing()
        self._ensure_storages()
        self.make_room()
        created = vmid is None
        if created:
            vmid = self.recorded_vmid() or int(self._command(["pvesh", "get", "/cluster/nextid"]).strip())
            self.create_root(vmid)
            self.create_data_disks(vmid, admin_gb, profiles_gb)
            self.create_vm(vmid, size, self.make_seed(vmid))
        if self.vm_status(vmid) != "running":
            self._command(["qm", "start", str(vmid)])
        self.wait_for_agent(vmid)
        creds = self.credentials(passphrase)
        self.run_install(vmid, creds)               # a no-op in the guest when it is already installed
        state = {"vmid": vmid, "kasm_version": manifest.get("kasm_version"), "base_sha256": manifest.get("sha256"), "installed": True, **size}
        self.layout.record.parent.mkdir(parents=True, exist_ok=True)
        self.layout.record.write_text(json.dumps(state, indent=1))
        return {**state, "created": created, "url": self.address(vmid)}

    def carried_workspaces(self):
        """The workspaces the carried base says it holds (its manifest), or None when there is no readable manifest."""
        try:
            rows = json.loads((self.layout.base_dir / "KASM.json").read_text()).get("workspaces")
        except (OSError, ValueError):
            return None
        return rows if isinstance(rows, list) else None

    def status(self) -> dict:
        """What is there now, without changing anything."""
        vmid = self.existing_vmid()
        record = self.read_record()
        if vmid is None:
            return {"present": False, "installed": False, "recorded_vmid": self.recorded_vmid(), "workspaces": self.carried_workspaces()}
        running = self.vm_status(vmid) == "running"
        return {"present": True, "vmid": vmid, "running": running, "installed": bool(record.get("installed")),
                "url": self.address(vmid) if running else None, "memory_mb": record.get("memory_mb"), "cpus": record.get("cpus"),
                "workspaces": self.carried_workspaces()}

    def reset_root(self) -> dict:
        """Throw the OS away and boot a new one over the same base; the admin and profile disks are not touched (the persistence proof)."""
        vmid = self.existing_vmid()
        if vmid is None:
            raise KasmSetupError("there is no Kasm VM to reset")
        self.check_volumes()
        self.check_base()
        if self.vm_status(vmid) != "stopped":
            self._command(["qm", "shutdown", str(vmid), "--timeout", "120", "--forceStop", "1"])
        root = self._disk_path(self.layout.root_dir, vmid, 0)
        if root.is_symlink():
            raise KasmSetupError("the root disk is a link; refusing to replace it")
        root.unlink(missing_ok=True)
        self.create_root(vmid)
        self._command(["qm", "start", str(vmid)])
        self.wait_for_agent(vmid)
        return {"vmid": vmid, "url": self.address(vmid)}

