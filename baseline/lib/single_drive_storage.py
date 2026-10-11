"""Identity-bound storage inspection and offline provisioning for one installation.

Physical writes require the existing device validator. A matching serial alone
is insufficient: the mounted target root and every PV in its VG must match too.
"""
import json
import hashlib
import os
import re

import physical_device_safety as pds
import repair
import drive_installer as di
import self_installer
import storage_policy


class StorageError(RuntimeError):
    pass


def isolate_volume_group(runner, *, expected_serial, pds_runner=None):
    """Rename only the selected offline disk's sole-PV VG by UUID.

    Boot configuration must subsequently be updated and boot-tested. Never
    selects a VG by the ambiguous installer default name alone.
    """
    import drive_recovery
    if not isinstance(expected_serial,str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}",expected_serial):
        raise StorageError("a selected hardware serial is required")
    uid = runner.run(["id","-u"],timeout=10)
    if uid.returncode or uid.stdout.strip() != "0":
        raise StorageError("complete device-use inspection requires root")
    disk = drive_recovery._offline_disk(runner,expected_serial)
    target = pds.validate_target_device(disk["name"],expected_serial=expected_serial,
        min_size_bytes=disk["size"],max_size_bytes=disk["size"],runner=pds_runner)
    candidates = [n["name"] for n in _walk(disk.get("children",[]))
                  if n.get("type")=="part" and n.get("fstype")=="LVM2_member"]
    if len(candidates)!=1:raise StorageError("selected disk must have exactly one physical volume")
    pv = candidates[0]
    used = runner.run(["fuser","--",target["path"],pv],timeout=15)
    if used.returncode!=1 or used.stdout.strip():raise StorageError("selected disk or PV is in use")
    command = ["pvs","--devices",pv,"--reportformat","json","-o",
               "pv_name,pv_uuid,vg_name,vg_uuid,pv_count"]
    def inventory():
        data = _json_command(runner,command)
        try:
            rows = data["report"][0]["pv"]
            if len(rows)!=1 or rows[0]["pv_name"]!=pv or int(rows[0]["pv_count"])!=1:
                raise ValueError
            row = rows[0]
            if any(not isinstance(row.get(k),str) or not re.fullmatch(r"[A-Za-z0-9_.+-]+",row[k])
                   for k in ("pv_uuid","vg_uuid","vg_name")):raise ValueError
            return row
        except (KeyError,IndexError,TypeError,ValueError):
            raise StorageError("selected VG must have exactly one physical volume with known identity") from None
    before = inventory()
    name = "baseline_"+hashlib.sha256(expected_serial.encode()).hexdigest()[:12]
    if before["vg_name"] != name:
        all_vgs = _json_command(runner,["vgs","--reportformat","json","-o","vg_name,vg_uuid"])
        try:
            rows = all_vgs["report"][0]["vg"]
            if not isinstance(rows,list):raise ValueError
            if any(r["vg_name"]==name and r["vg_uuid"]!=before["vg_uuid"] for r in rows):
                raise StorageError("proposed VG name belongs to another drive")
        except (KeyError,IndexError,TypeError,ValueError):
            raise StorageError("global VG identity inventory is malformed") from None
        fresh = drive_recovery._offline_disk(runner,expected_serial)
        checked = pds.validate_target_device(fresh["name"],expected_serial=expected_serial,
            min_size_bytes=target["size_bytes"],max_size_bytes=target["size_bytes"],runner=pds_runner)
        if checked!=target or inventory()!=before:raise StorageError("selected PV identity changed")
        used = runner.run(["fuser","--",target["path"],pv],timeout=15)
        if used.returncode!=1 or used.stdout.strip():raise StorageError("selected disk or PV became active")
        changed = runner.run(["vgrename","--devices",pv,before["vg_uuid"],name],timeout=60)
        if changed.returncode:raise StorageError("selected VG rename failed: "+changed.stderr.strip())
    after = inventory()
    if after!={**before,"vg_name":name}:raise StorageError("VG rename identity verification failed")
    return {"serial":expected_serial,"pv_path":pv,"pv_uuid":after["pv_uuid"],
            "vg_uuid":after["vg_uuid"],"vg_name":name,
            "state":"identity-isolated-boot-update-required","boot_verified":False}


def _json_command(runner, argv):
    proc = runner.run(argv, timeout=30)
    if proc.returncode:
        raise StorageError(f"{argv[0]} inspection failed: {proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout)
    except (ValueError, TypeError):
        raise StorageError(f"{argv[0]} returned malformed inspection data") from None


def _walk(nodes):
    if not isinstance(nodes, list):
        raise StorageError("invalid block-device listing")
    for node in nodes:
        if not isinstance(node, dict):
            raise StorageError("invalid block-device entry")
        yield node
        yield from _walk(node.get("children", []))


def _backing_disk(runner, source, serial):
    if not isinstance(source, str) or not source.startswith("/dev/"):
        raise StorageError("root or PV does not identify a local block device")
    found = _json_command(runner, ["lsblk", "-s", "-J", "-p", "-o", "NAME,TYPE,SERIAL", source])
    disks = {node.get("name"): node.get("serial") for node in _walk(found.get("blockdevices"))
             if node.get("type") == "disk"}
    if len(disks) != 1 or list(disks.values()) != [serial]:
        raise StorageError("root/PV backing disk differs from the selected serial or is ambiguous")
    return next(iter(disks))


def inspect_target(runner, *, expected_serial, root_mount):
    if not isinstance(expected_serial, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", expected_serial):
        raise StorageError("a selected hardware serial is required")
    if (not isinstance(root_mount, str) or not os.path.isabs(root_mount)
            or os.path.normpath(root_mount) != root_mount or any(c in root_mount for c in "\x00\n")):
        raise StorageError("target root must be a clean absolute mountpoint")
    listing = _json_command(runner, ["lsblk", "-J", "-b", "-p", "-o", "NAME,TYPE,SERIAL,SIZE"])
    matches = [d for d in _walk(listing.get("blockdevices"))
               if d.get("type") == "disk" and d.get("serial") == expected_serial]
    if len(matches) != 1 or type(matches[0].get("size")) is not int or matches[0]["size"] <= 0:
        raise StorageError("selected serial must resolve to exactly one measured physical disk")
    disk = matches[0]
    mounts = _json_command(runner, ["findmnt", "-J", "--mountpoint", root_mount,
                                   "-o", "TARGET,SOURCE,FSTYPE,UUID"]).get("filesystems")
    if (not isinstance(mounts, list) or len(mounts) != 1 or not isinstance(mounts[0], dict)
            or mounts[0].get("target") != root_mount or mounts[0].get("fstype") != "ext4"
            or not mounts[0].get("uuid")):
        raise StorageError("target root is not one mounted ext4 filesystem with known identity")
    root = mounts[0]
    if _backing_disk(runner, root.get("source"), expected_serial) != disk.get("name"):
        raise StorageError("target root is on a different device")
    root_lvs = _json_command(runner, ["sudo", "-n", "lvs", "--reportformat", "json",
                                      "-o", "vg_name,vg_uuid,lv_name", root["source"]])
    try:
        roots = root_lvs["report"][0]["lv"]
        if not isinstance(roots, list) or len(roots) != 1 or roots[0]["lv_name"] != "root" or not roots[0]["vg_uuid"]:
            raise ValueError
        root_vg = roots[0]
    except (KeyError, IndexError, TypeError, ValueError):
        raise StorageError("target root does not identify exactly one host root LV") from None
    data = _json_command(runner, ["sudo", "-n", "pvs", "--reportformat", "json", "-o", "pv_name,pv_uuid,vg_name,vg_uuid"])
    try:
        rows = data["report"][0]["pv"]
        if not isinstance(rows, list) or any(not isinstance(p, dict) for p in rows):raise ValueError
        selected = [p for p in rows if p.get("vg_uuid") == root_vg["vg_uuid"]]
    except (KeyError, IndexError, TypeError, ValueError):
        raise StorageError("PV inventory is incomplete") from None
    if len(selected) != 1:
        raise StorageError("independent installation requires exactly one PV on its selected disk")
    pv = selected[0]
    if (_backing_disk(runner, pv.get("pv_name"), expected_serial) != disk["name"]
            or pv.get("vg_name") != root_vg["vg_name"]):
        raise StorageError("root VG backing identity is inconsistent")
    if (not pv.get("pv_uuid") or not pv.get("vg_uuid") or not re.fullmatch(r"[A-Za-z0-9_.+-]+", pv["vg_name"])
            or sum(p.get("vg_uuid") == pv["vg_uuid"] for p in rows) != 1):
        raise StorageError("selected VG has unknown identity or spans multiple PVs")
    return {"path": disk["name"], "serial": expected_serial, "size_bytes": disk["size"],
            "root_mount": root_mount, "root_source": root["source"], "root_uuid": root["uuid"],
            "pv_path": pv["pv_name"], "pv_uuid": pv["pv_uuid"],
            "vg_name": pv["vg_name"], "vg_uuid": pv["vg_uuid"]}


class OfflineRunner(repair.Runner):
    """Scope LVM to one PV and filesystem operations to one offline root.

    No shell or chroot is needed for storage. Only LVs created successfully by
    this runner may be formatted; interrupted creation is never formatted on retry.
    Device and mounted-root identity are rechecked before each mutation.
    """
    def __init__(self, runner, target, *, pds_runner=None):
        if target["root_mount"] == "/":
            raise StorageError("offline provisioning cannot target the running root")
        self.runner, self.target, self.pds_runner = runner, dict(target), pds_runner
        self.created = set()

    def _guard(self):
        checked = pds.validate_target_device(self.target["path"], expected_serial=self.target["serial"],
            min_size_bytes=self.target["size_bytes"], max_size_bytes=self.target["size_bytes"], runner=self.pds_runner)
        if checked["path"] != self.target["path"]:
            raise StorageError("target device path changed")
        if inspect_target(self.runner, expected_serial=self.target["serial"], root_mount=self.target["root_mount"]) != self.target:
            raise StorageError("target root/PV identity changed")

    def _path(self, path):
        if not isinstance(path, str) or not path.startswith("/") or os.path.normpath(path) != path:
            raise StorageError("invalid target filesystem path")
        actual = self.target["root_mount"].rstrip("/") + path
        if not os.path.realpath(actual).startswith(self.target["root_mount"].rstrip("/") + "/"):
            raise StorageError("target filesystem path escapes through a symlink")
        return actual

    def run(self, argv, timeout=10):
        argv = list(argv)
        if argv[:2] == ["sudo", "-n"]:argv = argv[2:]
        command = argv[0]
        if command not in {"lvs", "vgs", "lvcreate", "mkfs.ext4", "mkdir", "mount", "blkid", "findmnt"}:
            raise StorageError("unsupported offline storage command")
        if command == "mkfs.ext4" and argv[-1] not in self.created:
            raise StorageError("only a volume created by this operation may be formatted")
        if command in {"lvcreate", "mkfs.ext4", "mkdir", "mount"}:
            self._guard()
        if command in {"lvs", "vgs", "lvcreate"}:
            argv.extend(["--devices", self.target["pv_path"]])
        if command in {"mkdir", "mount"}:
            argv[-1] = self._path(argv[-1])
        if command == "findmnt":
            argv[argv.index("--mountpoint") + 1] = self._path(argv[argv.index("--mountpoint") + 1])
        proc = self.runner.run(argv, timeout=timeout)
        if command == "lvcreate" and proc.returncode == 0:
            self.created.add(f"/dev/{self.target['vg_name']}/{argv[argv.index('-n') + 1]}")
        return proc

    def path_exists(self, path):return self.runner.path_exists(self._path(path))
    def read_text(self, path):return self.runner.read_text(self._path(path))
    def write_text_atomic(self, path, content):
        self._guard()
        return self.runner.write_text_atomic(self._path(path), content)
    def append_text(self, path, content):
        self._guard()
        return self.runner.append_text(self._path(path), content)


def provision_target(runner, *, expected_serial, root_mount, required_bytes,
                     personas=di.DEFAULT_PERSONAS, growth_percent=20, pds_runner=None,
                     recovery_folder=None, planned_sizes_gib=None, reserve_bytes=None):
    """Provision measured roles on an offline installed target; never reinstall it."""
    volumes = di.baseline_volumes_for(tuple(personas))
    if (not isinstance(required_bytes, dict) or set(required_bytes) != {v[3] for v in volumes}
            or any(type(value) is not int or value < 0 for value in required_bytes.values())):
        raise StorageError("complete nonnegative role measurements are required before provisioning")
    target = inspect_target(runner, expected_serial=expected_serial, root_mount=root_mount)
    profile = self_installer.single_drive_profile(target["size_bytes"], personas=tuple(personas),
        growth_percent=growth_percent, required_bytes=required_bytes)
    if recovery_folder is None:
        raise StorageError("a verified whole-drive recovery snapshot is required before target writes")
    import drive_recovery
    recovered = drive_recovery.verify_snapshot(runner, recovery_folder, expected_serial=expected_serial)
    if recovered["size_bytes"] != target["size_bytes"]:
        raise StorageError("recovery snapshot does not match the measured target size")
    reserve = profile["storage"]["growth_bytes"] + profile["storage"]["safety_bytes"]
    if ((planned_sizes_gib is not None and planned_sizes_gib != profile["storage"]["volumes_gib"])
            or (reserve_bytes is not None and reserve_bytes != reserve)):
        raise StorageError("compiled capacity differs from measurements; review the measured profile before applying")
    bound = OfflineRunner(runner, target, pds_runner=pds_runner)
    bound._guard()
    return _apply_roles(bound, target, profile=profile, reserve=reserve, required_bytes=required_bytes,
                        personas=personas, growth_percent=growth_percent)


def measure_host(runner, target, personas):
    """What Proxmox's installer actually made on this drive (grow-on-demand plans from this, not from a preset): root, swap and thin-data
    sizes in whole GiB, and the bytes the host holds in the volume group (everything allocated except the Baseline role volumes)."""
    vg = target["vg_name"]
    rows = _json_command(runner, ["lvs", "--reportformat", "json", "--units", "b", "--nosuffix", "-o", "lv_name,lv_size", vg])
    stats = _json_command(runner, ["vgs", "--reportformat", "json", "--units", "b", "--nosuffix", "-o", "vg_size,vg_free", vg])
    try:
        sizes = {row["lv_name"]: int(row["lv_size"]) for row in rows["report"][0]["lv"]}
        group = stats["report"][0]["vg"][0]
        allocated = int(group["vg_size"]) - int(group["vg_free"])
        installer = {"lvm_maxroot": sizes["root"] // 1024**3, "lvm_swapsize": sizes["swap"] // 1024**3,
                     "lvm_maxvz": sizes["data"] // 1024**3}
    except (KeyError, IndexError, TypeError, ValueError):
        raise StorageError("the installed host volumes could not be measured") from None
    role_bytes = sum(sizes.get(v[0], 0) for v in di.baseline_volumes_for(tuple(personas)))
    return installer, allocated - role_bytes


def _apply_roles(bound, target, *, profile, reserve, required_bytes, personas, growth_percent, grow=None):
    """Shared by the offline and first-boot modes: create the role volumes, then persist identity and policy."""
    expected_serial = target["serial"]
    volumes = di.baseline_volumes_for(tuple(personas))
    host = _json_command(bound, ["lvs", "--reportformat", "json", "--units", "b", "--nosuffix",
                                 "-o", "lv_name,lv_size,lv_attr", target["vg_name"]])
    try:
        rows = host["report"][0]["lv"]
        sizes = {row["lv_name"]: int(row["lv_size"]) for row in rows}
        attributes = {row["lv_name"]: row["lv_attr"] for row in rows}
        if len(sizes) != len(rows) or not attributes["data"].startswith("t"):raise ValueError
        for name, key in (("root", "lvm_maxroot"), ("swap", "lvm_swapsize")):
            if sizes[name] < profile["installer_sizes"][key] * 1024**3:raise ValueError
        if sizes["data"] < profile["thin_data_min_bytes"]:raise ValueError
    except (KeyError, IndexError, TypeError, ValueError):
        raise StorageError("host root/swap/physical thin pool do not meet the single-drive profile") from None
    result = di.ensure_baseline_volumes(bound, vg_name=target["vg_name"], personas=tuple(personas),
        planned_sizes_gib=profile["storage"]["volumes_gib"],
        reserve_bytes=reserve,
        # A reinstall lands new volumes on an earlier install's filesystem signatures; those are in unallocated space, owned
        # by no existing volume, and lvcreate would otherwise refuse (seen on PC601, 2026-10-11).
        wipe_stale_signatures=True)
    failed = {label: item.detail for label, item in result.items() if not item.ok}
    if failed:
        raise StorageError("role provisioning incomplete; existing data left unformatted: " + json.dumps(failed))
    bindings = {}
    for name, _, _, label, mountpoint in volumes:
        proc = bound.run(["blkid", "-s", "UUID", "-o", "value", f"/dev/{target['vg_name']}/{name}"], timeout=15)
        if proc.returncode or not proc.stdout.strip():raise StorageError("provisioned role has no filesystem identity")
        identity = proc.stdout.strip()
        mounted = bound.run(["findmnt", "--mountpoint", mountpoint, "-n", "-o", "UUID"], timeout=15)
        if mounted.returncode or mounted.stdout.strip() != identity:
            raise StorageError("provisioned role is not mounted from its expected filesystem")
        bindings[label] = {"serial": expected_serial, "uuid": identity}
    extra = ({"policy_format": storage_policy.GROW_FORMAT, "installer_sizes": grow[0], "host_bytes": grow[1]} if grow else {})
    policy = storage_policy.build_policy(serial=expected_serial, size_bytes=target["size_bytes"],
        required_bytes=required_bytes, bindings=bindings, personas=personas, growth_percent=growth_percent, **extra)
    mount_labels = {v[4]: v[3] for v in volumes}
    lines = bound.read_text(di.FSTAB_PATH).splitlines() if bound.path_exists(di.FSTAB_PATH) else []
    retained = []
    for line in lines:
        fields = line.split()
        if fields and not line.lstrip().startswith("#") and len(fields) >= 2 and fields[1] in mount_labels:
            label = mount_labels[fields[1]]
            name = next(v[0] for v in volumes if v[3] == label)
            if fields[0] not in {f"/dev/{target['vg_name']}/{name}", "UUID=" + bindings[label]["uuid"]}:
                raise StorageError("target fstab already routes a role to an unexpected device")
        else:retained.append(line)
    for _, _, _, label, mountpoint in volumes:
        retained.append(f"UUID={bindings[label]['uuid']} {mountpoint} ext4 {di.mount_options_for(label)} 0 2")
    bound.write_text_atomic(di.FSTAB_PATH, "\n".join(retained) + "\n")
    storage_policy.save_policy(bound, storage_policy.POLICY_PATH, policy)
    bound.write_text_atomic("/etc/baseline/independent-drive.json", json.dumps({
        "serial": expected_serial, "root_uuid": target["root_uuid"], "vg_uuid": target["vg_uuid"],
        "pv_uuid": target["pv_uuid"], "policy_path": storage_policy.POLICY_PATH}, indent=2) + "\n")
    return {"state": "provisioned", "serial": expected_serial,
            "policy": policy, "created_roles": [label for label, item in result.items() if item.created],
            "boot_verified": False}


def serial_of_root_disk(ancestry):
    """The one physical disk under the running root, from `lsblk -s -J -p -o NAME,TYPE,SERIAL <root source>`."""
    disks = [n for n in _walk(ancestry.get("blockdevices")) if n.get("type") == "disk"]
    serials = {n.get("serial") for n in disks}
    if len(disks) != 1 or len(serials) != 1:
        raise StorageError("the running root must sit on exactly one physical disk")
    serial = disks[0].get("serial")
    if not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", serial):
        raise StorageError("the running root's disk reports no usable hardware serial")
    return serial


class RunningRunner(OfflineRunner):
    """First-boot storage on the freshly installed system itself.

    Same command allow-list, PV scoping and created-only formatting rule as OfflineRunner. Instead of re-validating
    a separate offline device, it re-inspects the running root's disk/VG/PV identity before every mutation.
    """
    def __init__(self, runner, target):
        if target.get("root_mount") != "/":
            raise StorageError("first-boot provisioning applies only to the running root")
        self.runner, self.target, self.pds_runner = runner, dict(target), None
        self.created = set()

    def _guard(self):
        if inspect_target(self.runner, expected_serial=self.target["serial"], root_mount="/") != self.target:
            raise StorageError("running root/PV identity changed")


def running_target(runner):
    mounts = _json_command(runner, ["findmnt", "-J", "--mountpoint", "/", "-o", "TARGET,SOURCE,FSTYPE,UUID"])
    try:
        source = mounts["filesystems"][0]["source"]
    except (KeyError, IndexError, TypeError):
        raise StorageError("the running root has no identifiable source") from None
    ancestry = _json_command(runner, ["lsblk", "-s", "-J", "-p", "-o", "NAME,TYPE,SERIAL", source])
    return inspect_target(runner, expected_serial=serial_of_root_disk(ancestry), root_mount="/")


def provision_first_boot(runner, *, required_bytes, personas=di.DEFAULT_PERSONAS, growth_percent=20, grow_on_demand=False):
    """Lay out Baseline's role volumes from the installed system's own first boot (self-contained installer).

    Only free VG space is used; only volumes created by this run are formatted, so an existing role is never
    reformatted and a rerun completes what is missing. Same profile, policy and fstab as the offline mode.
    """
    volumes = di.baseline_volumes_for(tuple(personas))
    if (not isinstance(required_bytes, dict) or set(required_bytes) != {v[3] for v in volumes}
            or any(type(value) is not int or value < 0 for value in required_bytes.values())):
        raise StorageError("complete nonnegative role measurements are required before provisioning")
    target = running_target(runner)
    grow = measure_host(runner, target, personas) if grow_on_demand else None
    profile = self_installer.single_drive_profile(target["size_bytes"], personas=tuple(personas),
        growth_percent=growth_percent, required_bytes=required_bytes,
        **({"grow_on_demand": True, "installer_sizes": grow[0], "host_bytes_measured": grow[1]} if grow else {}))
    reserve = profile["storage"]["growth_bytes"] + profile["storage"]["safety_bytes"]
    bound = RunningRunner(runner, target)
    bound._guard()
    return _apply_roles(bound, target, profile=profile, reserve=reserve, required_bytes=required_bytes,
                        personas=personas, growth_percent=growth_percent, grow=grow)


def reconcile_proxmox_storage(runner):
    """Repair the installer's obsolete default VG reference after serial isolation.

    Never redirect an existing or foreign VG. Use Proxmox's cluster config lock
    and native writer, then read back the actual storage configuration.
    """
    verified = storage_policy.verify_runtime(runner)
    target = inspect_target(runner, expected_serial=verified['serial'], root_mount='/')
    expected = target['vg_name']
    argv = ['pvesh', 'get', '/storage/local-lvm', '--output-format', 'json']
    config = _json_command(runner, argv)
    if config.get('type') != 'lvmthin' or config.get('thinpool') != 'data':
        raise StorageError('installer storage type/pool changed; refusing reconciliation')
    if config.get('vgname') != expected:
        if config.get('vgname') != 'pve':
            raise StorageError('native storage references an unexpected VG')
        inventory = _json_command(runner, ['vgs', '--select', 'vg_name=pve',
                                          '--reportformat', 'json', '-o', 'vg_name'])
        try:
            if inventory['report'][0]['vg']:
                raise StorageError('the original VG still exists; refusing to redirect its storage')
        except (KeyError, IndexError, TypeError):
            raise StorageError('original VG absence could not be established') from None
        # Repeat serial/root/PV/VG inspection immediately before config mutation.
        if inspect_target(runner, expected_serial=verified['serial'], root_mount='/') != target:
            raise StorageError('selected root/VG identity changed')
        script = '''my $name = shift @ARGV;
PVE::Storage::lock_storage_config(sub {
    my $cfg = PVE::Storage::config();
    my $s = $cfg->{ids}->{'local-lvm'};
    die "storage changed" unless $s && $s->{type} eq 'lvmthin'
        && $s->{thinpool} eq 'data' && $s->{vgname} eq 'pve';
    $s->{vgname} = $name;
    PVE::Storage::write_config($cfg);
});'''
        proc = runner.run(['perl', '-MPVE::Storage', '-e', script, expected], timeout=30)
        if proc.returncode:
            raise StorageError('native locked storage reconciliation failed')
    actual = _json_command(runner, argv)
    if actual.get('vgname') != expected or actual.get('type') != 'lvmthin' or actual.get('thinpool') != 'data':
        raise StorageError('native storage binding did not verify')
    return {'state': 'native_storage_verified', 'serial': verified['serial'], 'vg_name': expected}
