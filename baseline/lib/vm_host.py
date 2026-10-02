"""VM host: base images, copy-on-write overlays, start/stop and rollback, directly on QEMU/KVM (no Proxmox needed).

Layout under the disposable store: bases/<name>.qcow2, vms/<name>/vm.json
and an overlay disk.qcow2. The separate protected store holds standalone
system.qcow2 disks and overlay home.qcow2 disks.
A VM is either "standalone" (its own disk, installed from an ISO) or an "overlay" (a qcow2 whose backing file is a
base, so the base is never written and a rollback is just recreating the overlay).

Safety rules: names are strict and every path is built from the store, never from user text; a VM disk is only ever a
file inside the configured stores (never a block device); a process is stopped by asking the guest to power down, then QMP quit,
and only as a last resort by signalling the exact recorded pid after its command line is checked to be our qemu.
Everything external is injected so tests never start qemu.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

GIB = 2**30
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
DEFAULT_STORE = Path("/mnt/BASELINE/vm-runtime")
DEFAULT_PERSISTENCE_STORE = Path("/mnt/USER_ADMIN/vm-data")
DEFAULT_ISO_DIR = Path("/mnt/INSTALLER_CACHE/isos")
FREE_HEADROOM = 10 * GIB
VM_NICENESS = 10      # Proxmox and its own guests (nice 0) win any CPU contention against VMs started here
OVMF_CODE = Path("/usr/share/OVMF/OVMF_CODE_4M.fd")
OVMF_VARS = Path("/usr/share/OVMF/OVMF_VARS_4M.fd")


class VmError(Exception):
    pass


def valid_name(name) -> bool:
    return isinstance(name, str) and bool(NAME_RE.match(name))


def list_isos(iso_dir) -> list:
    d = Path(iso_dir)
    if not d.is_dir():
        return []
    return [{"name": p.name, "path": str(p), "size": p.stat().st_size} for p in sorted(d.glob("*.iso"))]


def default_display(env) -> str:
    return "gtk" if env.get("WAYLAND_DISPLAY") or env.get("DISPLAY") else "vnc"


def _real_run(argv):
    r = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout, r.stderr


def low_priority(argv: list) -> list:
    return ["nice", "-n", str(VM_NICENESS)] + list(argv)


def _real_spawn(argv) -> int:
    return subprocess.Popen(low_priority(argv), start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).pid


def _real_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


def _real_cmdline(pid: int) -> list:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\0")
    except OSError:
        return []


def _real_kill(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)


def _real_qmp(sock_path: str, command: str) -> None:
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(5)
        s.connect(sock_path)
        s.recv(4096)
        s.sendall(b'{"execute":"qmp_capabilities"}\n')
        s.recv(4096)
        s.sendall(json.dumps({"execute": command}).encode() + b"\n")
        try:
            s.recv(4096)
        except OSError:
            pass


def _real_free(path) -> int:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


class VmHost:
    def __init__(self, store, *, run=_real_run, spawn=_real_spawn, is_alive=_real_alive, qmp=_real_qmp,
                 kill=_real_kill, sleep=time.sleep, free_bytes=_real_free, cmdline=_real_cmdline, runtime_dir=None,
                 persistence_store=DEFAULT_PERSISTENCE_STORE):
        self.store = Path(store)
        self.persistence_store = Path(persistence_store)
        self.runtime_dir = Path(runtime_dir) if runtime_dir else Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "baseline-vms"
        self.run, self.spawn, self.is_alive, self.qmp, self.kill = run, spawn, is_alive, qmp, kill
        self.sleep, self.free_bytes, self._cmdline = sleep, free_bytes, cmdline

    # ---- paths -------------------------------------------------------------------------------------------------
    @property
    def bases_dir(self) -> Path:
        return self.store / "bases"

    @property
    def vms_dir(self) -> Path:
        return self.store / "vms"

    def sock_path(self, name: str) -> Path:
        """QMP socket, kept in a short runtime dir: a unix socket path must be under 108 bytes."""
        self._need_name(name)
        tag = hashlib.sha1(str(self.store).encode()).hexdigest()[:8]
        return self.runtime_dir / f"{name}-{tag}.sock"

    def vm_dir(self, name: str) -> Path:
        self._need_name(name)
        return self.vms_dir / name

    def base_path(self, name: str) -> Path:
        self._need_name(name)
        return self.bases_dir / f"{name}.qcow2"

    def disk_path(self, name: str) -> Path:
        if (self.vm_dir(name) / "vm.json").is_file():
            spec = self._spec(name)
            if spec.get("root_disk"):
                if Path(spec["root_disk"]) != self.standalone_path(name):
                    raise VmError("unexpected standalone disk location")
                return self.standalone_path(name)
        return self.vm_dir(name) / "disk.qcow2"

    def standalone_path(self, name: str) -> Path:
        self._need_name(name)
        return self.persistence_store / name / "system.qcow2"

    def persistence_path(self, name: str) -> Path:
        self._need_name(name)
        return self.persistence_store / name / "home.qcow2"

    def configure_uefi(self, name: str) -> None:
        spec = self._need_stopped(name)
        if not OVMF_CODE.is_file() or not OVMF_VARS.is_file():
            raise VmError("UEFI firmware is missing; install the ovmf package")
        variables = self.vm_dir(name) / "firmware-vars.fd"
        if not variables.exists():
            shutil.copyfile(OVMF_VARS, variables)
        spec["uefi"] = True
        self._write_spec(name, spec)

    @staticmethod
    def _need_name(name) -> None:
        if not valid_name(name):
            raise VmError("names are lowercase letters, digits and dashes (1-32, not starting with a dash)")

    def _spec(self, name: str) -> dict:
        path = self.vm_dir(name) / "vm.json"
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            raise VmError(f"no such VM: {name}") from None

    def _write_spec(self, name: str, spec: dict) -> None:
        (self.vm_dir(name) / "vm.json").write_text(json.dumps(spec, indent=1))

    # ---- creation ----------------------------------------------------------------------------------------------
    @staticmethod
    def _check_store(path: Path) -> None:
        resolved = path.resolve()
        if "INSTALLER_CACHE" in resolved.parts:
            raise VmError("INSTALLER_CACHE is for vanilla downloads; VM state must use a separate volume")
        if resolved.is_relative_to("/mnt"):
            mount = Path("/mnt") / resolved.parts[2] if len(resolved.parts) > 2 else Path("/mnt")
            if not os.path.ismount(mount):
                raise VmError(f"{mount} must be mounted before storing VM state")

    def _new_dir(self, name: str, size_gb: int) -> Path:
        self._check_store(self.store)
        d = self.vm_dir(name)
        if d.exists():
            raise VmError(f"a VM named {name} already exists")
        if self.free_bytes(self.store) < FREE_HEADROOM + size_gb * GIB // 10:
            raise VmError("not enough free space in the VM store for this VM")
        d.mkdir(parents=True)
        return d

    def _create_disk(self, d: Path, argv: list) -> None:
        rc, _out, err = self.run(argv)
        if rc != 0:
            shutil.rmtree(d, ignore_errors=True)
            raise VmError(f"qemu-img failed: {err.strip()[:300]}")

    def create_from_iso(self, name: str, *, iso: str, disk_gb: int, memory_mb: int = 4096, cpus: int = 2) -> dict:
        self._need_name(name)
        if not (1 <= int(disk_gb) <= 4096 and 256 <= int(memory_mb) <= 1048576 and 1 <= int(cpus) <= 128):
            raise VmError("disk, memory or cpu count out of range")
        self._check_store(self.store)
        self._check_store(self.persistence_store)
        if self.persistence_store.resolve().is_relative_to(self.store.resolve()) or self.store.resolve().is_relative_to(self.persistence_store.resolve()):
            raise VmError("protected disks must be outside the disposable VM store")
        if self.free_bytes(self.persistence_store) < FREE_HEADROOM + int(disk_gb) * GIB // 10:
            raise VmError("not enough free space for the standard VM disk")
        d = self._new_dir(name, 0)
        root = self.standalone_path(name)
        if root.parent.exists():
            shutil.rmtree(d)
            raise VmError("retained state already exists; refusing to replace it")
        root.parent.mkdir(parents=True)
        try:
            self._create_disk(root.parent, ["qemu-img", "create", "-f", "qcow2", str(root), f"{int(disk_gb)}G"])
        except Exception:
            shutil.rmtree(d, ignore_errors=True)
            raise
        spec = {"name": name, "base": None, "iso": str(iso), "iso_done": False, "memory_mb": int(memory_mb),
                "cpus": int(cpus), "disk_gb": int(disk_gb), "root_disk": str(root)}
        self._write_spec(name, spec)
        return spec

    def create_overlay(self, name: str, *, base: str, memory_mb: int = 4096, cpus: int = 2,
                       persistence_gb: int = 32) -> dict:
        self._need_name(name)
        if not (256 <= int(memory_mb) <= 1048576 and 1 <= int(cpus) <= 128 and 1 <= int(persistence_gb) <= 4096):
            raise VmError("memory, cpu count or user disk size out of range")
        self._check_store(self.persistence_store)
        if self.persistence_store.resolve().is_relative_to(self.store.resolve()) or self.store.resolve().is_relative_to(self.persistence_store.resolve()):
            raise VmError("user data must be outside the disposable VM store")
        bpath = self.base_path(base)
        if not bpath.is_file():
            raise VmError(f"no such base image: {base}")
        d = self._new_dir(name, 0)
        # The backend may allocate a Proxmox VMID in _new_dir, so resolve
        # the retained volume only after that allocation.
        data_path = self.persistence_path(name)
        data_dir = data_path.parent
        if data_dir.exists():
            shutil.rmtree(d)
            raise VmError(f"{name} has retained user data; explicitly reattach it instead of replacing it")
        self._create_disk(d, ["qemu-img", "create", "-f", "qcow2", "-b", str(bpath), "-F", "qcow2",
                              str(self.disk_path(name))])
        if self.free_bytes(self.persistence_store) < FREE_HEADROOM + int(persistence_gb) * GIB // 10:
            shutil.rmtree(d)
            raise VmError("not enough free space for the retained user disk")
        try:
            data_dir.mkdir(parents=True)
            self._create_disk(data_dir, ["qemu-img", "create", "-f", "qcow2", str(data_path),
                                         f"{int(persistence_gb)}G"])
        except Exception:
            shutil.rmtree(d, ignore_errors=True)
            raise
        spec = {"name": name, "base": base, "iso": None, "iso_done": True, "memory_mb": int(memory_mb),
                "cpus": int(cpus), "disk_gb": None, "persistence_disk": str(data_path),
                "persistence_gb": int(persistence_gb)}
        self._write_spec(name, spec)
        return spec

    # ---- running -----------------------------------------------------------------------------------------------
    def _pidfile(self, name: str) -> Path:
        return self.vm_dir(name) / "vm.pid"

    def _recorded_pid(self, name: str):
        try:
            return int(json.loads(self._pidfile(name).read_text())["pid"])
        except (OSError, ValueError, KeyError):
            return None

    def _is_our_qemu(self, name: str, pid) -> bool:
        if pid is None or not self.is_alive(pid):
            return False
        args = " ".join(self._cmdline(pid))
        return "qemu-system" in args and str(self.disk_path(name)) in args

    def status(self, name: str) -> dict:
        spec = self._spec(name)
        pid = self._recorded_pid(name)
        running = self._is_our_qemu(name, pid)
        vnc = None
        if running:
            try:
                argv = json.loads(self._pidfile(name).read_text())["argv"]
                if "-vnc" in argv:
                    vnc = f"127.0.0.1:{5900 + int(argv[argv.index('-vnc') + 1].split(':')[1])}"
            except (OSError, ValueError, KeyError, IndexError):
                pass
        return {"name": name, "kind": "overlay" if spec.get("base") else "standalone", "base": spec.get("base"),
                "running": running, "pid": pid if running else None, "memory_mb": spec["memory_mb"],
                "cpus": spec["cpus"], "iso": spec.get("iso") if not spec.get("iso_done") else None, "vnc": vnc,
                "persistence_disk": spec.get("persistence_disk"), "persistence_gb": spec.get("persistence_gb")}

    def vnc_display_number(self, name: str) -> int:
        return int(hashlib.sha1(f"{self.store}/{name}".encode()).hexdigest()[:6], 16) % 90 + 10

    def qemu_argv(self, name: str, *, with_iso: bool | None = None, display: str = "gtk") -> list:
        self._check_store(self.store)
        spec = self._spec(name)
        d = self.vm_dir(name)
        argv = ["qemu-system-x86_64", "-name", name, "-enable-kvm", "-machine", "q35", "-cpu", "host",
                "-smp", str(spec["cpus"]), "-m", str(spec["memory_mb"]),
                "-drive", f"file={self.disk_path(name)},if=virtio,format=qcow2",
                "-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0",
                "-device", "qemu-xhci", "-device", "usb-tablet", "-vga", "virtio",
                "-display", "none" if display == "vnc" else display,
                "-qmp", f"unix:{self.sock_path(name)},server=on,wait=off"]
        if display == "vnc":
            argv += ["-vnc", f"127.0.0.1:{self.vnc_display_number(name)}"]
        if spec.get("uefi"):
            argv += ["-drive", f"if=pflash,format=raw,readonly=on,file={OVMF_CODE}",
                     "-drive", f"if=pflash,format=raw,file={d / 'firmware-vars.fd'}",
                     "-boot", "order=c"]
        if spec.get("persistence_disk"):
            self._check_store(self.persistence_store)
            data = Path(spec["persistence_disk"])
            if data.resolve() != self.persistence_path(name).resolve() or not data.is_file():
                raise VmError("retained user disk is missing or outside its store; refusing to boot without it")
            argv += ["-drive", f"file={data},if=none,id=home,format=qcow2",
                     "-device", "virtio-blk-pci,drive=home,serial=baseline-home"]
        if spec.get("seed"):
            argv += ["-drive", f"file={d / 'seed.iso'},media=cdrom,readonly=on"]
        if with_iso is None:
            with_iso = bool(spec.get("iso")) and not spec.get("iso_done")
        if with_iso and spec.get("iso"):
            argv += ["-cdrom", spec["iso"], "-boot", "d"]
        return argv

    def start(self, name: str, *, with_iso: bool | None = None, display: str = "gtk") -> dict:
        if self.status(name)["running"]:
            raise VmError(f"{name} is already running")
        argv = self.qemu_argv(name, with_iso=with_iso, display=display)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        pid = self.spawn(argv)
        self._pidfile(name).write_text(json.dumps({"pid": pid, "argv": argv}))
        self.sleep(0.5)
        status = self.status(name)
        if not status["running"]:
            self._pidfile(name).unlink(missing_ok=True)
            raise VmError(f"{name} failed to start; check QEMU, KVM access and available memory")
        return status

    def configure(self, name: str, *, memory_mb: int, cpus: int) -> dict:
        spec = self._need_stopped(name)
        if not (256 <= int(memory_mb) <= 1048576 and 1 <= int(cpus) <= 128):
            raise VmError("memory or cpu count out of range")
        spec["memory_mb"], spec["cpus"] = int(memory_mb), int(cpus)
        self._write_spec(name, spec)
        return self.status(name)

    def request_stop(self, name: str) -> dict:
        """Ask the guest to power down (ACPI) and return at once: the web server must never block on a guest."""
        if self._is_our_qemu(name, self._recorded_pid(name)):
            self._try_qmp(str(self.sock_path(name)), "system_powerdown")
        return self.status(name)

    def force_stop(self, name: str) -> dict:
        pid = self._recorded_pid(name)
        if self._is_our_qemu(name, pid):
            self._try_qmp(str(self.sock_path(name)), "quit")
            self._wait_gone(pid, 5)
            if self.is_alive(pid) and self._is_our_qemu(name, pid):
                self.kill(pid)
        if not self._is_our_qemu(name, pid):
            self._pidfile(name).unlink(missing_ok=True)
        return self.status(name)

    def eject_iso(self, name: str) -> None:
        spec = self._spec(name)
        spec["iso_done"] = True
        self._write_spec(name, spec)

    def stop(self, name: str, *, wait_s: int = 30) -> dict:
        pid = self._recorded_pid(name)
        sock = str(self.sock_path(name))
        if self._is_our_qemu(name, pid):
            self._try_qmp(sock, "system_powerdown")
            self._wait_gone(pid, wait_s)
            if self.is_alive(pid):
                self._try_qmp(sock, "quit")
                self._wait_gone(pid, 5)
            if self.is_alive(pid) and self._is_our_qemu(name, pid):
                self.kill(pid)
        try:
            self._pidfile(name).unlink()
        except FileNotFoundError:
            pass
        return self.status(name)

    def _try_qmp(self, sock: str, command: str) -> None:
        try:
            self.qmp(sock, command)
        except OSError:
            pass

    def _wait_gone(self, pid: int, wait_s: int) -> None:
        for _ in range(max(1, int(wait_s * 2))):
            if not self.is_alive(pid):
                return
            self.sleep(0.5)

    # ---- lifecycle ---------------------------------------------------------------------------------------------
    def _need_stopped(self, name: str) -> dict:
        spec = self._spec(name)
        if self.status(name)["running"]:
            raise VmError(f"{name} is running; stop it first")
        return spec

    def rollback(self, name: str) -> None:
        spec = self._need_stopped(name)
        if not spec.get("base"):
            raise VmError("only an overlay VM can be rolled back; a standalone VM has no base to return to")
        bpath = self.base_path(spec["base"])
        disk = self.disk_path(name)
        fresh = disk.with_name("disk.qcow2.new")
        rc, _o, err = self.run(["qemu-img", "create", "-f", "qcow2", "-b", str(bpath), "-F", "qcow2", str(fresh)])
        if rc != 0:
            fresh.unlink(missing_ok=True)
            raise VmError(f"qemu-img failed: {err.strip()[:300]}")
        os.replace(fresh, disk)

    def freeze_as_base(self, name: str, base_name: str) -> None:
        spec = self._need_stopped(name)
        if spec.get("base"):
            raise VmError("only a standalone VM can become a base image")
        target = self.base_path(base_name)
        if target.exists():
            raise VmError(f"a base image named {base_name} already exists")
        self.bases_dir.mkdir(parents=True, exist_ok=True)
        disk = self.disk_path(name)
        shutil.move(str(disk), str(target))
        os.chmod(target, 0o444)
        shutil.rmtree(self.vm_dir(name), ignore_errors=True)

    def delete_vm(self, name: str) -> None:
        spec = self._need_stopped(name)
        if spec.get("root_disk"):
            self.disk_path(name).unlink()
        shutil.rmtree(self.vm_dir(name))

    def delete_base(self, base_name: str) -> None:
        path = self.base_path(base_name)
        if not path.is_file():
            raise VmError(f"no such base image: {base_name}")
        users = [v["name"] for v in self.list_vms() if v["base"] == base_name]
        if users:
            raise VmError(f"base image in use by: {', '.join(users)}")
        os.chmod(path, 0o644)
        path.unlink()

    # ---- listing -----------------------------------------------------------------------------------------------
    def list_bases(self) -> list:
        if not self.bases_dir.is_dir():
            return []
        out = []
        for p in sorted(self.bases_dir.glob("*.qcow2")):
            if valid_name(p.stem):
                out.append({"name": p.stem, "size": p.stat().st_size,
                            "used_by": [v["name"] for v in self.list_vms() if v["base"] == p.stem]})
        return out

    def list_vms(self) -> list:
        if not self.vms_dir.is_dir():
            return []
        out = []
        for d in sorted(self.vms_dir.iterdir()):
            if valid_name(d.name) and (d / "vm.json").is_file():
                try:
                    out.append(self.status(d.name))
                except VmError:
                    continue
        return out
