"""Proxmox adapter for the VM library.

Proxmox owns VM lifecycle and consoles. qcow2 backing images and the OS/home
split are shared with the local file-image engine; this module never spawns
a parallel QEMU process. Directory storage is registered only on explicitly
mounted volumes. Existing storage definitions are never overwritten.

The current implementation keeps the VMID and home volume across an OS
rebuild. It refuses destructive retirement of machines with retained data;
Proxmox's qm destroy otherwise deletes all its owned disks.
"""
from __future__ import annotations

import json
import ipaddress
import shutil
import socket
import subprocess
from pathlib import Path

import vm_host as vh

OS_STORAGE = "baseline-os"
USER_STORAGE = "baseline-user"


def _input(argv, data):
    result = subprocess.run(argv, input=data, capture_output=True, timeout=75)
    return result.returncode, result.stdout.decode(errors='replace'), result.stderr.decode(errors='replace')


class ProxmoxVmHost(vh.VmHost):
    backend = "Proxmox"

    def __init__(self, *args, run_input=_input, **kwargs):
        super().__init__(*args, **kwargs)
        self.run_input = run_input

    def guest_exec(self, name, command, data=b''):
        """Bounded synchronous guest command. Secrets are stdin only; no raw error output."""
        self._check_store(self.store)
        self._check_store(self.persistence_store)
        spec, record = self._spec(name), self._record(name)
        if not record['registered'] or not self.status(name)['running']:
            raise vh.VmError('guest operation requires a running registered environment')
        if (spec.get('recipe') not in ('ubuntu-desktop','ubuntu-server')
                or Path(spec.get('persistence_disk','')) != self.persistence_path(name)
                or not self.persistence_path(name).is_file() or self.persistence_path(name).is_symlink()):
            raise vh.VmError('guest operation requires the managed Ubuntu retained-home recipe')
        stores = json.loads(self._command(['pvesh','get','/storage','--output-format','json']))
        for ident,path in ((OS_STORAGE,self.store),(USER_STORAGE,self.persistence_store)):
            matches=[s for s in stores if s.get('storage')==ident]
            if len(matches)!=1 or matches[0].get('type')!='dir' or Path(matches[0].get('path','')).resolve()!=path.resolve():
                raise vh.VmError('native storage identity changed; guest operation refused')
        config = dict(line.split(': ',1) for line in
                      self._command(['qm','config',str(record['vmid'])]).splitlines() if ': ' in line)
        vmid = record['vmid']
        root = f'{OS_STORAGE}:{vmid}/{self.disk_path(name).name}'
        home = f'{USER_STORAGE}:{vmid}/{self.persistence_path(name).name}'
        if (config.get('name')!=name or config.get('lock')
                or config.get('virtio0','').split(',')[0]!=root
                or config.get('virtio1','').split(',')[0]!=home
                or 'serial=baseline-home' not in config.get('virtio1','').split(',')):
            raise vh.VmError('native VM identity or retained-home attachment changed; guest operation refused')
        rc, out, _ = self.run_input(['qm','guest','exec',str(vmid),'--pass-stdin','1',
                                    '--synchronous','1','--timeout','60','--',*command],data)
        try:
            result = json.loads(out)
        except (ValueError,TypeError):
            result = {}
        if (rc or not isinstance(result,dict) or result.get('exited') not in (True,1)
                or isinstance(result.get('exitcode'),bool) or result.get('exitcode')!=0
                or result.get('signal')):
            raise vh.VmError('guest command did not finish successfully; no success is inferred')
        return result


    def guest_homepage(self):
        """Use the bridge shared with guests, independent of an SSH tunnel
        or the browser's loopback hostname. Unknown means operator input."""
        try:
            rc, out, _ = self.run(["ip", "-j", "address", "show", "dev", "vmbr0"])
            if rc:
                return ""
            for interface in json.loads(out):
                for item in interface.get("addr_info", []):
                    if item.get("family") == "inet" and item.get("scope") == "global":
                        addr = ipaddress.IPv4Address(item["local"])
                        if not addr.is_loopback and not addr.is_link_local and not addr.is_unspecified:
                            return f"https://{addr}:8006"
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return ""

    def available_isos(self):
        node = socket.gethostname().split(".")[0]
        stores = json.loads(self._command(["pvesh", "get", "/storage", "--output-format", "json"]))
        result = []
        for store in stores:
            if "iso" not in str(store.get("content", "")).split(",") or store.get("disable"):
                continue
            ident = store["storage"]
            items = json.loads(self._command(["pvesh", "get", f"/nodes/{node}/storage/{ident}/content",
                                              "--content", "iso", "--output-format", "json"]))
            for item in items:
                volid = item["volid"]
                path = self._command(["pvesm", "path", volid]).strip()
                result.append({"name": volid, "path": path, "size": int(item.get("size", 0))})
        return result

    def _command(self, argv):
        rc, out, err = self.run(argv)
        if rc:
            raise vh.VmError(f"{argv[0]} {argv[1]} failed: {err.strip()[-400:]}")
        return out

    @property
    def names_dir(self):
        return self.persistence_store / "control" / "machines"

    def _record_path(self, name):
        self._need_name(name)
        return self.names_dir / f"{name}.json"

    def _record(self, name):
        try:
            record = json.loads(self._record_path(name).read_text())
            vmid = record["vmid"]
            if isinstance(vmid, bool) or not isinstance(vmid, int) or not 100 <= vmid <= 999999999:
                raise ValueError("invalid VMID")
            return record
        except (OSError, ValueError, KeyError, TypeError):
            raise vh.VmError(f"no such Proxmox environment: {name}") from None

    def _save_record(self, name, record):
        self.names_dir.mkdir(parents=True, exist_ok=True)
        self._record_path(name).write_text(json.dumps(record))

    def vm_dir(self, name):
        return self.store / "images" / str(self._record(name)["vmid"])

    def disk_path(self, name):
        vmid = self._record(name)["vmid"]
        if (self.vm_dir(name) / "vm.json").is_file() and self._spec(name).get("root_disk"):
            return super().disk_path(name)
        return self.vm_dir(name) / f"vm-{vmid}-disk-0.qcow2"

    def standalone_path(self, name):
        vmid = self._record(name)["vmid"]
        return self.persistence_store / "images" / str(vmid) / f"vm-{vmid}-disk-0.qcow2"

    def persistence_path(self, name):
        vmid = self._record(name)["vmid"]
        return self.persistence_store / "images" / str(vmid) / f"vm-{vmid}-disk-1.qcow2"

    def _ensure_storage(self):
        self._check_store(self.store)
        self._check_store(self.persistence_store)
        definitions = json.loads(self._command(["pvesh", "get", "/storage", "--output-format", "json"]))
        for ident, path, content in (
            (OS_STORAGE, self.store, "images,iso"),
            (USER_STORAGE, self.persistence_store, "images"),
        ):
            existing = next((d for d in definitions if d.get("storage") == ident), None)
            if existing is not None:
                if existing.get("type") != "dir" or Path(existing.get("path", "")).resolve() != path.resolve():
                    raise vh.VmError(f"storage {ident} already exists with a different type or path")
            else:
                argv = ["pvesm", "add", "dir", ident, "--path", str(path), "--content", content]
                if path.resolve().is_relative_to("/mnt"):
                    argv += ["--is_mountpoint", str(Path("/mnt") / path.resolve().parts[2])]
                self._command(argv)

    def create_overlay(self, name, **kwargs):
        spec = super().create_overlay(name, **kwargs)
        self._register(name, spec)
        return spec

    def _new_dir(self, name, size_gb):
        if self._record_path(name).exists():
            raise vh.VmError(f"{name} already exists or has retained state; refusing to replace it")
        self._ensure_storage()
        vmid = int(self._command(["pvesh", "get", "/cluster/nextid"]).strip())
        if not 100 <= vmid <= 999999999:
            raise vh.VmError("Proxmox returned an invalid VMID")
        self._save_record(name, {"vmid": vmid, "registered": False})
        try:
            return super()._new_dir(name, size_gb)
        except Exception:
            self._record_path(name).unlink(missing_ok=True)
            raise

    def create_from_iso(self, name, **kwargs):
        spec = super().create_from_iso(name, **kwargs)
        self._register(name, spec)
        return spec

    def _register(self, name, spec):
        record = self._record(name)
        vmid = record["vmid"]
        argv = ["qm", "create", str(vmid), "--name", name, "--memory", str(spec["memory_mb"]),
                "--cores", str(spec["cpus"]), "--machine", "q35", "--cpu", "host",
                "--vga", "virtio", "--net0", "virtio,bridge=vmbr0", "--agent", "enabled=1",
                "--virtio0", f"{USER_STORAGE if spec.get('root_disk') else OS_STORAGE}:{vmid}/{self.disk_path(name).name}",
                "--boot", "order=virtio0"]
        if spec.get("persistence_disk"):
            argv += ["--virtio1", f"{USER_STORAGE}:{vmid}/{self.persistence_path(name).name},serial=baseline-home"]
        if spec.get("iso"):
            source = Path(spec["iso"])
            # Cached ISOs are read-only sources; Proxmox gets a copy under
            # its ISO storage, never a mutable disk under INSTALLER_CACHE.
            iso_dir = self.store / "template" / "iso"
            iso_dir.mkdir(parents=True, exist_ok=True)
            target = iso_dir / f"{name}-installer.iso"
            shutil.copyfile(source, target)
            argv += ["--ide2", f"{OS_STORAGE}:iso/{target.name},media=cdrom", "--boot", "order=ide2;virtio0"]
        self._command(argv)
        record["registered"] = True
        self._save_record(name, record)

    def _write_spec(self, name, spec):
        super()._write_spec(name, spec)
        record = self._record(name)
        if record["registered"]:
            argv = ["qm", "set", str(record["vmid"]), "--memory", str(spec["memory_mb"]), "--cores", str(spec["cpus"])]
            if spec.get("seed"):
                iso_dir = self.store / "template" / "iso"
                iso_dir.mkdir(parents=True, exist_ok=True)
                target = iso_dir / f"{name}-seed.iso"
                shutil.copyfile(self.vm_dir(name) / "seed.iso", target)
                argv += ["--ide2", f"{OS_STORAGE}:iso/{target.name},media=cdrom"]
            elif spec.get("iso_done"):
                argv += ["--delete", "ide2", "--boot", "order=virtio0"]
            self._command(argv)
            if spec.get("disk_gb"):
                self._command(["qm", "disk", "rescan", "--vmid", str(record["vmid"])])

    def configure_uefi(self, name):
        spec = self._need_stopped(name)
        record = self._record(name)
        argv = ["qm", "set", str(record["vmid"]), "--bios", "ovmf"]
        if not record.get("efi_created"):
            argv += ["--efidisk0", f"{OS_STORAGE}:0,efitype=4m,pre-enrolled-keys=0"]
        self._command(argv)
        record["efi_created"] = True
        self._save_record(name, record)
        spec["uefi"] = True
        super()._write_spec(name, spec)

    def status(self, name):
        spec, record = self._spec(name), self._record(name)
        running = False
        if record["registered"]:
            output = self._command(["qm", "status", str(record["vmid"])]).strip()
            if output not in ("status: running", "status: stopped"):
                raise vh.VmError(f"unexpected Proxmox status: {output}")
            running = output == "status: running"
        return {"name": name, "vmid": record["vmid"], "kind": "overlay" if spec.get("base") else "standalone",
                "base": spec.get("base"), "running": running, "pid": None, "vnc": None,
                "memory_mb": spec["memory_mb"], "cpus": spec["cpus"],
                "iso": spec.get("iso") if not spec.get("iso_done") else None,
                "persistence_disk": spec.get("persistence_disk"), "persistence_gb": spec.get("persistence_gb"),
                "recipe": spec.get("recipe")}

    def start(self, name, **kwargs):
        self._check_store(self.store)
        self._check_store(self.persistence_store)
        spec = self._need_stopped(name)
        if spec.get("persistence_disk") and not self.persistence_path(name).is_file():
            raise vh.VmError("retained user disk is missing; refusing to boot")
        self._command(["qm", "start", str(self._record(name)["vmid"])])
        result = self.status(name)
        if not result["running"]:
            raise vh.VmError("Proxmox start did not result in a running VM")
        return result

    def request_stop(self, name):
        vmid = self._record(name)["vmid"]
        node = socket.gethostname().split(".")[0]
        self._command(["pvesh", "create", f"/nodes/{node}/qemu/{vmid}/status/shutdown"])
        return self.status(name)

    def force_stop(self, name):
        self._command(["qm", "stop", str(self._record(name)["vmid"])])
        result = self.status(name)
        if result["running"]:
            raise vh.VmError("Proxmox did not stop the VM")
        return result

    def stop(self, name, *, wait_s=30):
        self._command(["qm", "shutdown", str(self._record(name)["vmid"]), "--timeout", str(wait_s)])
        return self.status(name)

    def delete_vm(self, name):
        spec = self._need_stopped(name)
        if spec.get("persistence_disk"):
            raise vh.VmError("this VM has retained data; use rebuild, destructive retirement is not implemented")
        self._command(["qm", "destroy", str(self._record(name)["vmid"]), "--purge"])
        shutil.rmtree(self.vm_dir(name), ignore_errors=True)
        self._record_path(name).unlink()

    def freeze_as_base(self, name, base_name):
        record = self._record(name)
        super().freeze_as_base(name, base_name)
        self._command(["qm", "destroy", str(record["vmid"]), "--purge"])
        self._record_path(name).unlink()

    def list_vms(self):
        if not self.names_dir.is_dir():
            return []
        result = []
        for path in sorted(self.names_dir.glob("*.json")):
            if vh.valid_name(path.stem):
                if (self.vm_dir(path.stem) / "vm.json").is_file():
                    result.append(self.status(path.stem))
        return result
