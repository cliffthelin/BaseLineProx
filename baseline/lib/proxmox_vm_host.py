"""Proxmox adapter for the VM library.

Proxmox owns VM lifecycle and consoles. qcow2 backing images and the OS/home
split are shared with the local file-image engine; this module never spawns
a parallel QEMU process. Directory storage is registered only on explicitly
mounted volumes. Existing storage definitions are never overwritten.

The current implementation keeps the VMID and home volume across an OS
rebuild. Confirmed retirement validates the live VM configuration and storage
ownership before asking Proxmox to delete its managed disks.
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
HIDDEN_ISO_STORAGES = ("baseline-kasm-root",)      # holds the Kasm VM's own cloud-init seed, which is not an operating system anyone installs
USER_STORAGE = "baseline-user"


def _input(argv, data):
    result = subprocess.run(argv, input=data, capture_output=True, timeout=75)
    return result.returncode, result.stdout.decode(errors='replace'), result.stderr.decode(errors='replace')


def retirement_volumes(name, spec, record, config):
    """Return only this managed VM's owned volumes; reject any unowned disk."""
    if not isinstance(config, dict):
        raise vh.VmError('VM configuration is unavailable; retirement refused')
    volumes = managed_retirement_volumes(name, spec, record)
    vmid = record['vmid']
    if config.get('name') != name or config.get('lock'):
        raise vh.VmError('VM identity or lock changed; retirement refused')
    root_slot = 'sata0' if spec.get('source_base') == 'fydeos-base' else 'virtio0'
    if config.get(root_slot, '').split(',')[0] != volumes[0]:
        raise vh.VmError('managed root-disk attachment changed; retirement refused')
    home_expected = volumes[1] if spec.get('persistence_disk') else None
    if home_expected:
        if (config.get('virtio1', '').split(',')[0] != home_expected
                or 'serial=baseline-home' not in config.get('virtio1', '').split(',')):
            raise vh.VmError('retained-home attachment changed; retirement refused')
    elif config.get('virtio1'):
        raise vh.VmError('unexpected secondary VM disk; retirement refused')
    allowed_devices = {root_slot} | ({'virtio1'} if home_expected else set())
    efi_expected = next((volume for volume in volumes if volume.endswith(f'vm-{vmid}-disk-1.raw')), None)
    for key, value in config.items():
        if key == 'ide2' and value.startswith(f'{OS_STORAGE}:iso/') and 'media=cdrom' in value.split(','):
            continue
        if key == 'efidisk0' and efi_expected:
            if value.split(',')[0] != efi_expected:
                raise vh.VmError('EFI disk ownership changed; retirement refused')
            continue
        if key in allowed_devices:
            continue
        if key.startswith(('virtio', 'scsi', 'sata', 'ide', 'efidisk', 'unused')):
            raise vh.VmError(f'additional attached volume {key}; retirement refused')
    if bool(efi_expected) != bool(config.get('efidisk0')):
        raise vh.VmError('EFI disk attachment is missing; retirement refused')
    return volumes


def managed_retirement_volumes(name, spec, record):
    """Derive deterministic storage IDs from the durable Baseline VM identity."""
    vmid = record.get('vmid') if isinstance(record, dict) else None
    if isinstance(vmid, bool) or not isinstance(vmid, int) or not 100 <= vmid <= 999999999:
        raise vh.VmError('invalid VM identity; retirement refused')
    if not isinstance(spec, dict):
        raise vh.VmError('VM specification is unavailable; retirement refused')
    root_storage = USER_STORAGE if spec.get('root_disk') else OS_STORAGE
    root_name = Path(spec['root_disk']).name if spec.get('root_disk') else f'vm-{vmid}-disk-0.qcow2'
    root = f'{root_storage}:{vmid}/{root_name}'
    volumes = [root]
    if spec.get('persistence_disk'):
        home_name = Path(spec['persistence_disk']).name
        home = f'{USER_STORAGE}:{vmid}/{home_name}'
        volumes.append(home)
    if record.get('efi_created'):
        volumes.append(f'{OS_STORAGE}:{vmid}/vm-{vmid}-disk-1.raw')
    return volumes


def _cluster_resource(resources, vmid):
    """Resolve one VMID from Proxmox's live cluster inventory, failing closed."""
    if not isinstance(resources, list) or not all(isinstance(item, dict) for item in resources):
        raise vh.VmError('Proxmox returned an invalid cluster inventory; retirement refused')
    matches = [item for item in resources if item.get('vmid') == vmid]
    if len(matches) > 1:
        raise vh.VmError('VMID is ambiguous in Proxmox inventory; retirement refused')
    if matches and matches[0].get('type') != 'qemu':
        raise vh.VmError('VMID belongs to a non-VM workload; retirement refused')
    return matches[0] if matches else None


def _parse_qm_config(output):
    """Parse qm config output without hiding malformed or duplicate settings."""
    if not isinstance(output, str) or not output.strip():
        raise vh.VmError('Proxmox returned an empty VM configuration; retirement refused')
    config = {}
    for line in output.splitlines():
        if ': ' not in line:
            raise vh.VmError('Proxmox returned an invalid VM configuration; retirement refused')
        key, value = line.split(': ', 1)
        if not key or key in config:
            raise vh.VmError('Proxmox returned duplicate VM settings; retirement refused')
        config[key] = value
    return config


def guest_agent_recipe(spec) -> bool:
    """The machines Baseline made itself whose seed turns the guest agent on: the managed Ubuntu recipes and every ready-made system made with a seed (prebuilt-<system>)."""
    recipe = str(spec.get('recipe') or '')
    return recipe in ('ubuntu-desktop', 'ubuntu-server') or (recipe.startswith('prebuilt-') and spec.get('seed') is True)


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
        if (not guest_agent_recipe(spec)
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
        or the browser's loopback hostname. A failed probe is an error;
        only a successful probe with no usable IPv4 address returns empty."""
        try:
            rc, out, err = self.run(["ip", "-j", "address", "show", "dev", "vmbr0"])
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise vh.VmError(f"Proxmox homepage detection failed: {exc}") from exc
        if rc:
            detail = str(err).strip() if err else ""
            detail = detail or f"ip exited {rc}"
            raise vh.VmError(f"Proxmox homepage detection failed: {detail}")
        try:
            interfaces = json.loads(out)
        except (TypeError, ValueError) as exc:
            raise vh.VmError("Proxmox homepage detection returned invalid JSON") from exc
        if not isinstance(interfaces, list) or not all(isinstance(item, dict) for item in interfaces):
            raise vh.VmError("Proxmox homepage detection returned an invalid interface list")
        for interface in interfaces:
            addresses = interface.get("addr_info")
            if not isinstance(addresses, list):
                raise vh.VmError("Proxmox homepage detection returned invalid address details")
            for item in addresses:
                if not isinstance(item, dict):
                    raise vh.VmError("Proxmox homepage detection returned an invalid address entry")
                if item.get("family") == "inet" and item.get("scope") == "global":
                    try:
                        addr = ipaddress.IPv4Address(item["local"])
                    except (KeyError, ipaddress.AddressValueError) as exc:
                        raise vh.VmError("Proxmox homepage detection returned an invalid IPv4 address") from exc
                    if not addr.is_loopback and not addr.is_link_local and not addr.is_unspecified:
                        return f"https://{addr}:8006"
        return ""

    def available_isos(self):
        node = socket.gethostname().split(".")[0]
        stores = json.loads(self._command(["pvesh", "get", "/storage", "--output-format", "json"]))
        result = []
        for store in stores:
            if "iso" not in str(store.get("content", "")).split(",") or store.get("disable") or store.get("storage") in HIDDEN_ISO_STORAGES:
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

    def _expected_volume_path(self, volid, vmid):
        try:
            storage, identity = volid.split(':', 1)
            target_vmid, filename = identity.split('/', 1)
        except ValueError as exc:
            raise vh.VmError(f'invalid managed volume identity {volid!r}') from exc
        if (storage not in (OS_STORAGE, USER_STORAGE) or target_vmid != str(vmid)
                or not filename or Path(filename).name != filename or filename in ('.', '..')):
            raise vh.VmError(f'unmanaged volume identity {volid!r}; retirement refused')
        store = self.persistence_store if storage == USER_STORAGE else self.store
        return store / 'images' / str(vmid) / filename

    def _validate_volume_path(self, volid, vmid, *, must_exist=True):
        expected = self._expected_volume_path(volid, vmid)
        if expected.is_symlink():
            raise vh.VmError(f'managed volume is a symbolic link: {expected}')
        if not expected.exists() and not must_exist:
            return expected
        path_text = self._command(['pvesm', 'path', volid]).strip()
        actual = Path(path_text)
        if (not path_text or actual.is_symlink() or not actual.is_file()
                or actual.resolve() != expected.resolve()):
            raise vh.VmError(f'volume ownership or path changed for {volid}; retirement refused')
        return expected

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

    def create_retained_base(self, name, **kwargs):
        pre_existing = self._record_path(name).exists()
        try:
            spec = super().create_retained_base(name, **kwargs)
            self._register(name, spec)
            return spec
        except Exception:
            if not pre_existing:
                self._discard_unregistered(name)
            raise

    def create_overlay(self, name, **kwargs):
        pre_existing = self._record_path(name).exists()
        try:
            spec = super().create_overlay(name, **kwargs)
            self._register(name, spec)
        except Exception:
            if not pre_existing:
                self._discard_unregistered(name)
            raise
        return spec

    def _discard_unregistered(self, name):
        """A creation that failed before Proxmox knew the VM leaves nothing behind (the VMID record and the folders this attempt made), so the
        same name can be tried again. A VM Proxmox does know is never removed here."""
        record_path = self._record_path(name)
        if not record_path.exists():
            return
        record = self._record(name)
        if record.get("registered"):
            return
        vmid = record["vmid"]
        shutil.rmtree(self.persistence_store / "images" / str(vmid), ignore_errors=True)
        shutil.rmtree(self.store / "images" / str(vmid), ignore_errors=True)
        record_path.unlink(missing_ok=True)

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
                "--vga", "virtio-gl" if spec.get("graphics") == "virgl" else "virtio", "--net0", "virtio,bridge=vmbr0", "--agent", "enabled=1",
                "--virtio0", f"{USER_STORAGE if spec.get('root_disk') else OS_STORAGE}:{vmid}/{self.disk_path(name).name}",
                "--boot", "order=virtio0"]
        if spec.get('source_base') == 'fydeos-base':
            argv[argv.index('--virtio0')] = '--sata0'
            argv[argv.index('order=virtio0')] = 'order=sata0'
            argv[argv.index('--net0') + 1] = 'e1000,bridge=vmbr0'
            argv[argv.index('--agent') + 1] = 'enabled=0'
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
                argv += ["--delete", "ide2", "--boot", "order=sata0" if spec.get('source_base') == 'fydeos-base' else "order=virtio0"]
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
        self._check_store(self.store)
        self._check_store(self.persistence_store)
        spec = self._spec(name)
        record = self._record(name)
        vmid = record['vmid']
        resources = json.loads(self._command(['pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json']))
        resource = _cluster_resource(resources, vmid)
        if record.get('registered') and resource is None:
            # A prior confirmed delete can be resumed after Proxmox removed the
            # cluster object but before local metadata cleanup completed.
            record['registered'] = False
            self._save_record(name, record)
        elif not record.get('registered') and resource is not None:
            raise vh.VmError('VMID is registered in Proxmox but the Baseline record says otherwise; retirement refused')

        retirement = record.get('retirement')
        if retirement is not None and not isinstance(retirement, dict):
            raise vh.VmError('retirement record is invalid; cleanup refused')
        if resource is not None:
            node = resource.get('node')
            local_node = socket.gethostname().split('.')[0]
            if not isinstance(node, str) or node != local_node:
                raise vh.VmError('VM is not on this Proxmox node; retirement refused')
            status = self._command(['qm', 'status', str(vmid)]).strip()
            if status != 'status: stopped':
                raise vh.VmError('VM must be stopped before retirement')
            definitions = json.loads(self._command(['pvesh', 'get', '/storage', '--output-format', 'json']))
            if not isinstance(definitions, list) or not all(isinstance(item, dict) for item in definitions):
                raise vh.VmError('Proxmox returned invalid storage definitions; retirement refused')
            for ident, path in ((OS_STORAGE, self.store), (USER_STORAGE, self.persistence_store)):
                matches = [item for item in definitions if item.get('storage') == ident]
                if (len(matches) != 1 or matches[0].get('type') != 'dir'
                        or matches[0].get('disable')
                        or Path(matches[0].get('path', '')).resolve() != path.resolve()):
                    raise vh.VmError(f'native storage identity changed for {ident}; retirement refused')
            config = _parse_qm_config(self._command(['qm', 'config', str(vmid)]))
            volids = retirement_volumes(name, spec, record, config)
            paths = [str(self._validate_volume_path(volid, vmid)) for volid in volids]
            retirement = {'volumes': volids, 'paths': paths}
            record['retirement'] = retirement
            self._save_record(name, record)
            self._command(['qm', 'destroy', str(vmid), '--purge'])
            resources = json.loads(self._command(['pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json']))
            if _cluster_resource(resources, vmid) is not None:
                raise vh.VmError('Proxmox still reports the VM after destroy; retirement is incomplete')
            record['registered'] = False
            self._save_record(name, record)

        if retirement is None:
            volumes = managed_retirement_volumes(name, spec, record)
            paths = [str(self._validate_volume_path(volid, vmid, must_exist=False)) for volid in volumes]
            retirement = {'volumes': volumes, 'paths': paths}
            record['retirement'] = retirement
            self._save_record(name, record)

        if retirement:
            volumes, paths = retirement.get('volumes'), retirement.get('paths')
            if (not isinstance(volumes, list) or not isinstance(paths, list)
                    or len(volumes) != len(paths)
                    or volumes != managed_retirement_volumes(name, spec, record)):
                raise vh.VmError('retirement record does not match the managed VM; cleanup refused')
            for volid, saved_path in zip(volumes, paths):
                expected = self._expected_volume_path(volid, vmid)
                path = Path(saved_path)
                if path != expected:
                    raise vh.VmError(f'retirement path changed for {volid}; cleanup refused')
                if path.exists() or path.is_symlink():
                    if path.is_symlink() or not path.is_file():
                        raise vh.VmError(f'retired volume is not a regular managed file: {path}')
                    self._validate_volume_path(volid, vmid)
                    self._command(['pvesm', 'free', volid])
                    if path.exists():
                        raise vh.VmError(f'Proxmox did not remove retired volume {volid}')

        directory = self.vm_dir(name)
        if directory.exists():
            allowed = {'vm.json'} | ({'seed.iso', 'seed'} if spec.get('seed') else set())
            unexpected = sorted(child.name for child in directory.iterdir() if child.name not in allowed)
            if unexpected:
                raise vh.VmError(f'unrecognized files remain in VM directory: {", ".join(unexpected)}')
            for child in directory.iterdir():
                if child.is_symlink():
                    raise vh.VmError(f'unexpected symbolic link remains in VM directory: {child.name}')
                if child.is_dir() and child.name == 'seed' and spec.get('seed'):
                    seed_files = sorted(item.name for item in child.iterdir())
                    if seed_files != ['meta-data', 'user-data']:
                        raise vh.VmError('unrecognized files remain in VM seed directory')
                    for item in child.iterdir():
                        if item.is_symlink() or not item.is_file():
                            raise vh.VmError('unexpected non-file remains in VM seed directory')
                        item.unlink()
                    child.rmdir()
                elif child.is_file():
                    child.unlink()
                else:
                    raise vh.VmError(f'unexpected non-file remains in VM directory: {child.name}')
            directory.rmdir()
        for suffix, exists_in_spec in (('installer', bool(spec.get('iso'))), ('seed', bool(spec.get('seed')))):
            cached_iso = self.store / 'template' / 'iso' / f'{name}-{suffix}.iso'
            if not exists_in_spec and not cached_iso.exists() and not cached_iso.is_symlink():
                continue
            if cached_iso.is_symlink() or (cached_iso.exists() and not cached_iso.is_file()):
                raise vh.VmError(f'unexpected file remains in Proxmox ISO storage: {cached_iso.name}')
            cached_iso.unlink(missing_ok=True)
        for storage in (self.store, self.persistence_store):
            image_dir = storage / 'images' / str(vmid)
            if image_dir.exists():
                try:
                    image_dir.rmdir()
                except OSError as exc:
                    raise vh.VmError(f'unowned files remain in VM storage directory {image_dir}: {exc}') from exc
        self._record_path(name).unlink()
        self._record_path(name).unlink()

    def freeze_as_base(self, name, base_name):
        record = self._record(name)
        super().freeze_as_base(name, base_name)
        self._command(["qm", "destroy", str(record["vmid"]), "--purge"])
        self._record_path(name).unlink()

    def list_vms(self):
        self._check_store(self.store)
        self._check_store(self.persistence_store)
        if not self.names_dir.is_dir():
            return []
        result = []
        for path in sorted(self.names_dir.glob("*.json")):
            if vh.valid_name(path.stem):
                if (self.vm_dir(path.stem) / "vm.json").is_file():
                    result.append(self.status(path.stem))
        return result
