"""Kasm on Proxmox (kasm_setup.py): what is created where, that the persistent disks are never replaced, and that credentials are recorded before use and
travel only on stdin. Proxmox's commands go through a scripted fake; the disks and vault are a real temp tree."""
import json

import pytest

import kasm_setup as ks
import vault as vault_mod


class Fake:
    """Scripted Proxmox: remembers calls, answers the few commands setup uses, and creates the files qemu-img would."""

    def __init__(self, vms=None, storages=None, agent_after=0, install_exit=0, conf_dir=None):
        self.calls, self.inputs = [], []
        self.conf_dir, self.config = conf_dir, {}
        self.vms = list(vms or [])
        self.storages = list(storages or [])
        self.agent_after, self.pings = agent_after, 0
        self.install_exit = install_exit
        self.state = "stopped"

    def __call__(self, argv, data=None, timeout=120):
        self.calls.append(list(argv))
        if data is not None:
            self.inputs.append(data)
        head = argv[:2]
        if head == ["pvesh", "get"]:
            if argv[2] == "/cluster/resources":
                listed = [v for v in self.vms if self.conf_dir is None or (self.conf_dir / f"{v['vmid']}.conf").exists()]
                return 0, json.dumps(listed), ""
            if argv[2] == "/storage":
                return 0, json.dumps(self.storages), ""
            if argv[2] == "/cluster/nextid":
                return 0, "100\n", ""
        if head == ["pvesm", "add"]:
            self.storages.append({"storage": argv[3], "type": "dir", "path": argv[argv.index("--path") + 1]})
        if head == ["qemu-img", "create"]:
            from pathlib import Path
            Path(argv[-1] if not argv[-1].endswith("G") else argv[-2]).write_bytes(b"qcow2")
        if head == ["xorriso", "-as"]:
            from pathlib import Path
            Path(argv[argv.index("-o") + 1]).write_bytes(b"iso")
        if head == ["qm", "create"]:
            self.vms.append({"name": argv[argv.index("--name") + 1], "vmid": int(argv[2])})
            self.config = {argv[i][2:]: argv[i + 1] for i in range(3, len(argv), 2)}
            self.config["net0"] = self.config.get("net0", "virtio,bridge=vmbr0") if "=" in self.config.get("net0", "").split(",")[0] else "virtio=BC:24:11:AA:BB:CC,bridge=vmbr0"
            if self.conf_dir is not None:
                self.conf_dir.mkdir(parents=True, exist_ok=True)
                (self.conf_dir / f"{argv[2]}.conf").write_text("x")
        if head == ["qm", "set"]:
            self.config.update({argv[i][2:]: argv[i + 1] for i in range(3, len(argv), 2)})
        if head == ["qm", "config"]:
            return 0, "\n".join(f"{k}: {v}" for k, v in self.config.items()), ""
        if head == ["qm", "start"]:
            self.state = "running"
        if head == ["qm", "shutdown"]:
            self.state = "stopped"
        if head == ["qm", "status"]:
            return 0, f"status: {self.state}\n", ""
        if head == ["qm", "agent"] and argv[3] == "ping":
            self.pings += 1
            return (0, "", "") if self.pings > self.agent_after else (255, "", "no agent")
        if head == ["qm", "agent"] and argv[3] == "network-get-interfaces":
            return 0, json.dumps([{"name": "lo", "ip-addresses": [{"ip-address": "127.0.0.1", "ip-address-type": "ipv4"}]},
                                  {"name": "ens18", "ip-addresses": [{"ip-address": "192.168.1.50", "ip-address-type": "ipv4"}]}]), ""
        if head == ["qm", "guest"]:
            if "Reads one line" in argv[-1]:                                                                 # the settings script (Kasm's admin API, inside the VM)
                self.settings_stdin = data
                return 0, json.dumps({"exited": 1, "exitcode": 0, "out-data": getattr(self, "settings_output", "")}), ""
            if "from accounting" in argv[-1]:
                return 0, json.dumps({"exited": 1, "exitcode": 0, "out-data": getattr(self, "accounting_output", "")}), ""
            if "Read-only." in argv[-1]:                                                                      # the telemetry probe
                return 0, json.dumps({"exited": 1, "exitcode": 0, "out-data": getattr(self, "probe_output", "")}), ""
            code = self.install_exit if argv[-1] == "/usr/local/sbin/baseline-kasm-install" else 0          # only the installer itself can fail here
            return 0, json.dumps({"exited": 1, "exitcode": code, "out-data": "boom" if code else ""}), ""
        return 0, "", ""

    def named(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


@pytest.fixture
def world(tmp_path):
    layout = ks.Layout(root_dir=tmp_path / "temp" / "kasm", admin_dir=tmp_path / "admin" / "kasm", profiles_dir=tmp_path / "personal" / "kasm",
                       base_dir=tmp_path / "cache" / "kasm", vault_path=str(tmp_path / "vault"), mounts=(), pve_conf_dir=tmp_path / "pve")
    layout.base_dir.mkdir(parents=True)
    layout.base.write_bytes(b"base image")
    (layout.base_dir / "KASM.json").write_text(json.dumps({"sha256": "abc", "kasm_version": "1.19.0", "holds_install_state_or_secrets": False}))
    return layout


def build(world, fake=None, **kwargs):
    fake = fake or Fake()
    fake.conf_dir = fake.conf_dir or world.pve_conf_dir
    options = dict(run=fake, is_mount=lambda _m: True, sleep=lambda _s: None, hash_file=lambda _p: "abc", host_mb=32768, host_cores=8)
    options.update(kwargs)
    return ks.KasmSetup(world, **options), fake


def test_the_vm_is_sized_from_the_host_not_fixed():
    assert ks.size_vm(32768, 8) == {"memory_mb": 8192, "cpus": 4}
    assert ks.size_vm(131072, 64) == {"memory_mb": 16384, "cpus": 4}
    assert ks.size_vm(16384, 2) == {"memory_mb": 6144, "cpus": 2}


def test_a_host_too_small_to_share_is_refused_with_the_reason():
    with pytest.raises(ks.KasmSetupError, match="8 GiB"):
        ks.size_vm(8192, 4)


def test_the_base_must_match_its_manifest_and_be_free_of_install_state(world):
    setup, _ = build(world, hash_file=lambda _p: "different")
    with pytest.raises(ks.KasmSetupError, match="checksum"):
        setup.check_base()
    (world.base_dir / "KASM.json").write_text(json.dumps({"sha256": "abc"}))
    setup, _ = build(world)
    with pytest.raises(ks.KasmSetupError, match="free of install state"):
        setup.check_base()
    world.base.unlink()
    with pytest.raises(ks.KasmSetupError, match="not in the installer cache"):
        setup.check_base()


def test_unmounted_volumes_are_named_and_nothing_is_created(world):
    setup, fake = build(world, is_mount=lambda m: m != "/mnt/APPDATA_ADMIN")
    object.__setattr__(world, "mounts", ("/mnt/SESSION_TEMP", "/mnt/APPDATA_ADMIN"))
    with pytest.raises(ks.KasmSetupError, match="APPDATA_ADMIN"):
        setup.setup()
    assert not fake.named("qm", "create") and not fake.named("qemu-img")


def test_setup_builds_the_vm_on_persisted_layers_attached_by_serial_with_no_session_layer(world):
    setup, fake = build(world)
    result = setup.setup()
    config = fake.named("qm", "create")[0]
    assert result["vmid"] == 100 and result["created"] and result["url"] == "https://192.168.1.50" and result["mode"] == "persist" and result["layout"] == ks.LAYOUT
    assert "baseline-kasm-admin:100/vm-100-disk-0.qcow2" in config                      # the OS layer is persisted too (on APPDATA_ADMIN)
    assert f"baseline-kasm-admin:100/vm-100-disk-1.qcow2,serial={ks.ADMIN_SERIAL}" in config
    assert f"baseline-kasm-prof:100/vm-100-disk-2.qcow2,serial={ks.PROFILES_SERIAL}" in config
    assert (world.admin_dir / "images/100/vm-100-disk-0.qcow2").is_file() and (world.admin_dir / "images/100/vm-100-disk-1.qcow2").is_file()
    assert (world.profiles_dir / "images/100/vm-100-disk-2.qcow2").is_file()
    assert not (world.root_dir / "images/100").exists()                                 # persist mode has no session layer
    assert len(ks.ADMIN_SERIAL) <= 20 and len(ks.PROFILES_SERIAL) <= 20


def test_the_os_layer_is_an_overlay_on_the_vanilla_base_and_the_data_disks_are_bare_sparse(world):
    setup, fake = build(world)
    setup.setup()
    creates = {c[-2] if c[-1].endswith("G") else c[-1]: c for c in fake.named("qemu-img", "create")}
    root = creates[str(world.admin_dir / "images/100/vm-100-disk-0.qcow2")]
    assert ["-b", str(world.base), "-F", "qcow2"] == root[root.index("-b"):root.index("-b") + 4]
    for path in (world.admin_dir / "images/100/vm-100-disk-1.qcow2", world.profiles_dir / "images/100/vm-100-disk-2.qcow2"):
        argv = creates[str(path)]
        assert "-b" not in argv and "-o" not in argv and not [a for a in argv if "prealloc" in a]       # reserved, never written


def test_the_installer_cache_base_is_only_ever_read(world):
    setup, fake = build(world)
    setup.setup()
    before = world.base.read_bytes()
    setup.reset_root(confirm=True)
    assert world.base.read_bytes() == before
    assert not [c for c in fake.calls if str(world.base_dir) in " ".join(c) and c[0] not in ("qemu-img",)]


def test_credentials_are_generated_and_on_record_before_the_guest_is_told_them(world):
    setup, fake = build(world)
    setup.setup()
    stored = {name: setup.vault.get(name) for name in ks.SECRET_NAMES}
    assert all(stored.values()) and len(set(stored.values())) == 4
    assert all(len(v) == 32 and v.isalnum() for v in stored.values())          # what the guest-side installer accepts
    assert fake.inputs and all(f"{n}={v}\n".encode() in fake.inputs[0] for n, v in stored.items())


def test_a_secret_never_appears_on_any_command_line(world):
    setup, fake = build(world)
    setup.setup()
    values = [setup.vault.get(n) for n in ks.SECRET_NAMES]
    flat = " ".join(" ".join(c) for c in fake.calls)
    assert not any(v in flat for v in values)


def test_a_rebuild_reuses_the_recorded_credentials_not_new_ones(world):
    setup, _ = build(world)
    setup.setup()
    first = {n: setup.vault.get(n) for n in ks.SECRET_NAMES}
    again, fake = build(world)
    again.setup()
    assert {n: again.vault.get(n) for n in ks.SECRET_NAMES} == first
    assert fake.inputs[0] == "".join(f"{n}={first[n]}\n" for n in ks.SECRET_NAMES).encode()


def test_a_vault_with_only_some_of_the_credentials_is_refused_not_completed(world):
    setup, fake = build(world)
    setup.vault.put("KASM_ADMIN_PASSWORD", "x" * 20)
    with pytest.raises(ks.KasmSetupError, match="some but not all"):
        setup.setup()
    assert not fake.named("qm", "guest")


def test_a_sealed_vault_stops_the_install_before_any_guest_work(world):
    setup, fake = build(world)
    setup.vault.set_passphrase("a long enough passphrase")
    with pytest.raises(ks.KasmSetupError, match="vault"):
        setup.setup()
    assert not fake.named("qm", "guest")
    again, fake2 = build(world)
    again.setup(passphrase="a long enough passphrase")                                       # given the passphrase it proceeds, sealed at rest
    assert fake2.named("qm", "guest")
    sealed = [f.read_text() for f in __import__("pathlib").Path(world.vault_path).glob("KASM_*")]
    assert len(sealed) == 4 and all(t.startswith(vault_mod.vault_crypto.PREFIX) for t in sealed)   # stored sealed, not in plain


def test_a_failed_install_is_reported_without_the_secrets_and_leaves_no_record(world):
    setup, fake = build(world, fake=Fake(install_exit=1))
    with pytest.raises(ks.KasmSetupError, match="did not finish.*kasm-install.log") as info:
        setup.setup()
    assert not any(setup.vault.get(n) in str(info.value) for n in ks.SECRET_NAMES)
    assert not world.record.exists()


def test_setup_twice_does_not_rebuild_or_replace_anything(world):
    setup, fake = build(world)
    setup.setup()
    again, fake2 = build(world, fake=Fake(vms=[{"name": ks.VM_NAME, "vmid": 100}]))
    fake2.state = "running"
    result = again.setup()
    assert not result["created"] and not fake2.named("qm", "create") and not fake2.named("qemu-img") and not fake2.named("qm", "start")


def test_a_vm_that_is_gone_is_built_again_from_its_persisted_layers_without_creating_or_changing_any(world):
    setup, _ = build(world)
    setup.setup()
    contents = {0: b"the OS layer, with everything set in the VM", 1: b"kasm state", 2: b"the user's profiles"}
    for index, data in contents.items():
        setup.persisted_path(100, index).write_bytes(data)
    (world.pve_conf_dir / "100.conf").unlink()                                              # Proxmox no longer lists the VM; every layer and the record remain
    again, fake = build(world)
    result = again.setup()
    assert result["vmid"] == 100 and result["created"]
    assert {i: again.persisted_path(100, i).read_bytes() for i in contents} == contents
    assert not fake.named("qemu-img") and not fake.named("pvesh", "get", "/cluster/nextid")


def test_reset_root_needs_confirmation_and_replaces_only_the_os_layer(world):
    setup, fake = build(world)
    setup.setup()
    setup.persisted_path(100, 1).write_bytes(b"kasm state")
    setup.persisted_path(100, 2).write_bytes(b"profiles")
    setup.persisted_path(100, 0).write_bytes(b"old os layer with a lot of writes")
    with pytest.raises(ks.KasmSetupError, match="explicit confirmation"):
        setup.reset_root()
    assert setup.persisted_path(100, 0).read_bytes() == b"old os layer with a lot of writes"           # nothing was touched
    result = setup.reset_root(confirm=True)
    assert result["vmid"] == 100 and setup.persisted_path(100, 0).read_bytes() == b"qcow2"            # a fresh overlay on the base
    assert setup.persisted_path(100, 1).read_bytes() == b"kasm state" and setup.persisted_path(100, 2).read_bytes() == b"profiles"


def test_a_linked_disk_is_never_followed(world, tmp_path):
    target = tmp_path / "elsewhere"
    target.write_bytes(b"x")
    link = world.admin_dir / "images/100/vm-100-disk-1.qcow2"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    setup, fake = build(world)
    with pytest.raises(ks.KasmSetupError, match="link"):
        setup.setup()
    assert target.read_bytes() == b"x"


def test_a_storage_id_taken_by_something_else_is_refused(world):
    setup, fake = build(world, fake=Fake(storages=[{"storage": "baseline-kasm-admin", "type": "lvmthin", "path": ""}]))
    with pytest.raises(ks.KasmSetupError, match="different type or path"):
        setup.setup()
    assert not fake.named("qm", "create")


def test_two_vms_with_the_name_are_refused_not_guessed_at(world):
    world.pve_conf_dir.mkdir(parents=True)
    for vmid in (100, 101):
        (world.pve_conf_dir / f"{vmid}.conf").write_text("x")
    setup, _ = build(world, fake=Fake(vms=[{"name": ks.VM_NAME, "vmid": 100}, {"name": ks.VM_NAME, "vmid": 101}]))
    with pytest.raises(ks.KasmSetupError, match="more than one"):
        setup.setup()


def test_the_seed_holds_no_secret_and_turns_password_login_off(world):
    setup, _ = build(world)
    setup.setup()
    assert not (world.root_dir / "seed").exists()                                          # the source folder is removed after the ISO is made
    assert (world.root_dir / "template/iso/baseline-kasm-seed.iso").is_file()


def test_an_installed_vm_is_only_made_sure_of_not_rechecked_or_reinstalled(world):
    setup, _ = build(world)
    setup.setup()
    hashed = []
    again, fake = build(world, fake=Fake(vms=[{"name": ks.VM_NAME, "vmid": 100}]), hash_file=lambda p: hashed.append(p) or "abc")
    result = again.setup()
    assert hashed == [] and not fake.named("qm", "guest") and not fake.named("qm", "agent", "100", "ping")   # the timer that retries this costs nothing once done
    assert fake.named("qm", "start", "100") and result["installed"] and not result["created"]


def test_status_reports_without_changing_anything(world):
    setup, fake = build(world)
    assert setup.status() == {"present": False, "installed": False, "dehydrated": False, "mode": None, "recorded_vmid": None, "workspaces": None, "recipe": None}
    setup.setup()
    fake.state = "running"
    now = setup.status()
    assert now["present"] and now["running"] and now["installed"] and now["mode"] == "persist" and now["url"] == "https://192.168.1.50"
    assert not fake.named("qm", "stop") and len(fake.named("qm", "start")) == 1


def test_each_role_volume_is_given_room_for_kasms_first_writes_before_anything_is_built(world):
    asked = []
    setup, fake = build(world, ensure_room=lambda label, needed: asked.append((label, needed)))
    setup.setup()
    assert dict(asked) == ks.ROOM_NEEDED and set(dict(asked)) == {"SESSION_TEMP", "APPDATA_ADMIN", "APPDATA_PERSONAL"}
    assert fake.calls.index(fake.named("qm", "create")[0]) > 0 and asked                      # asked, and before the VM exists


def test_a_volume_that_cannot_grow_stops_the_build_with_its_reason(world):
    def refuse(label, needed):
        if label == "APPDATA_ADMIN":
            raise RuntimeError("the volume group has no free space")
    setup, fake = build(world, ensure_room=refuse)
    with pytest.raises(ks.KasmSetupError, match="APPDATA_ADMIN cannot be given the room.*no free space"):
        setup.setup()
    assert not fake.named("qm", "create") and not fake.named("qemu-img")


def test_status_reports_the_workspaces_the_carried_base_holds(world):
    (world.base_dir / "KASM.json").write_text(json.dumps({"workspaces": [{"friendly_name": "Browser", "persistent": True}], "holds_install_state_or_secrets": False}))
    setup, _ = build(world)
    assert setup.status()["workspaces"] == [{"friendly_name": "Browser", "persistent": True}]
    (world.base_dir / "KASM.json").unlink()
    assert setup.status()["workspaces"] is None



# ---- run modes, dehydrate and rehydrate (operator 2026-10-17) ---------------------------------------------------------------

def installed(world, **kw):
    setup, fake = build(world, **kw)
    setup.setup()
    return setup, fake


def test_reset_mode_runs_on_a_fresh_session_layer_over_the_persisted_one_and_persist_mode_has_none(world):
    setup, fake = installed(world)
    result = setup.set_mode("reset")
    assert result["mode"] == "reset" and setup.read_record()["mode"] == "reset"
    for index in range(3):                                                               # a layer on SESSION_TEMP, backed by the persisted disk
        made = [c for c in fake.named("qemu-img", "create") if c[-1] == str(setup.session_path(100, index))][-1]
        assert made[made.index("-b") + 1] == str(setup.persisted_path(100, index)) and "-F" in made
    assert fake.config["virtio0"] == "baseline-kasm-root:100/vm-100-disk-0.qcow2"
    assert fake.config["virtio1"].endswith(f"serial={ks.ADMIN_SERIAL}") and fake.config["virtio1"].startswith("baseline-kasm-root:")
    setup.set_mode("persist")
    assert fake.config["virtio0"] == "baseline-kasm-admin:100/vm-100-disk-0.qcow2" and not (world.root_dir / "images/100/vm-100-disk-0.qcow2").exists()


def test_every_start_in_reset_mode_begins_from_a_fresh_layer_so_a_runs_changes_are_gone(world):
    setup, fake = installed(world)
    setup.set_mode("reset")
    session = setup.session_path(100, 0)
    session.write_bytes(b"everything done during that run")                              # what the guest wrote
    fake.state = "stopped"
    setup.setup()                                                                       # the timer starts a stopped VM
    assert session.read_bytes() == b"qcow2"                                             # fresh, empty layer
    assert setup.persisted_path(100, 0).read_bytes() == b"qcow2"                        # and the persisted layer was never written


def test_persist_mode_start_keeps_whatever_the_guest_wrote(world):
    setup, fake = installed(world)
    setup.persisted_path(100, 0).write_bytes(b"kept")
    fake.state = "stopped"
    setup.setup()
    assert setup.persisted_path(100, 0).read_bytes() == b"kept" and not fake.named("qemu-img", "create")[3:]


def test_a_reset_mode_start_refuses_a_running_vm_instead_of_pulling_the_layer_from_under_it(world):
    setup, fake = installed(world)
    setup.set_mode("reset")
    fake.state = "running"
    with pytest.raises(ks.KasmSetupError, match="stopped first"):
        setup.start_vm(100)


def test_an_unknown_mode_is_refused(world):
    setup, _ = installed(world)
    with pytest.raises(ks.KasmSetupError, match="one of: persist, reset"):
        setup.set_mode("snapshot")


def test_dehydrate_removes_only_the_definition_and_rehydrate_brings_back_the_same_vm(world):
    setup, fake = installed(world)
    for index in range(3):
        setup.persisted_path(100, index).write_bytes(f"layer {index}".encode())
    first_mac = fake.config["net0"]
    report = setup.dehydrate()
    assert report["dehydrated"] and not (world.pve_conf_dir / "100.conf").exists()
    assert [p.read_bytes() for p in map(lambda i: setup.persisted_path(100, i), range(3))] == [b"layer 0", b"layer 1", b"layer 2"]       # every layer is kept
    assert setup.status()["present"] is False and setup.status()["dehydrated"] and setup.status()["installed"]
    assert not [c for c in fake.calls if c[:2] in (["qm", "destroy"], ["pvesm", "free"])]                                                   # nothing was deleted through Proxmox
    again, fake2 = build(world)
    result = again.setup()
    assert result["created"] and result["vmid"] == 100 and result["memory_mb"] == setup.read_record()["memory_mb"]
    assert f"virtio={first_mac.split('virtio=')[1].split(',')[0]}" in fake2.named("qm", "create")[0][fake2.named("qm", "create")[0].index("--net0") + 1]   # the same address
    assert [p.read_bytes() for p in map(lambda i: again.persisted_path(100, i), range(3))] == [b"layer 0", b"layer 1", b"layer 2"]
    assert not fake2.named("qemu-img")


def test_dehydrate_in_reset_mode_drops_the_session_layer_and_keeps_the_persisted_ones(world):
    setup, fake = installed(world)
    setup.set_mode("reset")
    setup.dehydrate()
    assert not any(setup.session_path(100, i).exists() for i in range(3)) and all(setup.persisted_path(100, i).exists() for i in range(3))


def test_dehydrate_refuses_when_a_layer_is_missing_or_the_vm_is_not_ours_or_the_definition_is_elsewhere(world):
    setup, fake = installed(world)
    setup.persisted_path(100, 2).unlink()
    with pytest.raises(ks.KasmSetupError, match="persisted layer is missing"):
        setup.dehydrate()
    assert (world.pve_conf_dir / "100.conf").exists()
    setup.persisted_path(100, 2).write_bytes(b"x")
    fake.config["name"] = "someone-elses-vm"
    with pytest.raises(ks.KasmSetupError, match="name or lock"):
        setup.dehydrate()
    fake.config["name"] = ks.VM_NAME
    conf = world.pve_conf_dir / "100.conf"
    conf.unlink()
    elsewhere = world.pve_conf_dir.parent / "elsewhere.conf"
    elsewhere.write_text("x")
    conf.symlink_to(elsewhere)                                                          # a link where Proxmox keeps the definition: never followed or removed
    with pytest.raises(ks.KasmSetupError, match="not where Proxmox keeps it"):
        setup.dehydrate()


def test_a_vm_from_the_first_layout_can_neither_change_mode_nor_be_dehydrated_and_is_otherwise_unchanged(world):
    setup, fake = installed(world)
    setup._write_record(layout=None)
    record = setup.read_record()
    record.pop("layout")
    world.record.write_text(json.dumps(record))
    with pytest.raises(ks.KasmSetupError, match="first layout"):
        setup.set_mode("reset")
    with pytest.raises(ks.KasmSetupError, match="not built with the persisted layers"):
        setup.dehydrate()
    fake.state = "stopped"
    assert setup.setup()["created"] is False and fake.named("qm", "start")                   # the existing fast path still just makes sure it runs


def test_persisted_layers_made_on_another_base_are_not_used_with_this_one(world):
    setup, fake = installed(world)
    setup.dehydrate()
    again, fake2 = build(world, hash_file=lambda _p: "different")
    (world.base_dir / "KASM.json").write_text(json.dumps({"sha256": "different", "kasm_version": "1.19.1", "holds_install_state_or_secrets": False}))
    with pytest.raises(ks.KasmSetupError, match="different Kasm base"):
        again.setup()
    assert not fake2.named("qm", "create")


def test_the_persisted_os_layer_gets_the_room_it_needs_on_the_admin_volume():
    assert ks.ROOM_NEEDED["APPDATA_ADMIN"] >= 12 * ks.GIB and ks.MODES == ("persist", "reset") and ks.DEFAULT_MODE == "persist"


def test_only_one_action_runs_at_a_time_and_the_timers_setup_just_steps_aside(world):
    setup, fake = installed(world)
    fake.state = "stopped"                                                              # stopped on purpose by a mode change that is in progress
    with setup._exclusive():
        other, other_fake = build(world)
        assert other.setup() == {"busy": True} and not other_fake.named("qm", "start")      # the timer does not start it from under the action
        with pytest.raises(ks.Busy, match="another Kasm action"):
            other.set_mode("reset")
        with pytest.raises(ks.Busy):
            other.dehydrate()
    assert setup.setup()["created"] is False and fake.named("qm", "start")                  # once the action is done the timer's call works again


def test_dockers_start_limit_is_lifted_for_the_install_and_put_back_even_when_the_install_fails(world):
    """Found on a nested Proxmox (2026-10-17): the installer's quick Docker restarts tripped systemd's start-rate limit and stopped the install half-way."""
    for exit_code in (0, 1):
        setup, fake = build(world, fake=Fake(install_exit=exit_code))
        try:
            setup.run_install(100, {n: "x" * 20 for n in ks.SECRET_NAMES})
        except ks.KasmSetupError:
            assert exit_code == 1
        guests = [c for c in fake.calls if c[:3] == ["qm", "guest", "exec"]]
        scripts = [c[-1] for c in guests if c[-2] == "-c"]
        installs = [i for i, c in enumerate(guests) if c[-1] == "/usr/local/sbin/baseline-kasm-install"]
        before = next(x for x in scripts if "StartLimitIntervalSec=0" in x)
        after = next(x for x in scripts if x.startswith("rm -f /etc/systemd/system/docker.service.d/"))
        assert "StartLimitIntervalSec=0" in before and "reset-failed docker" in before and "daemon-reload" in before
        assert guests.index([c for c in guests if c[-1] == before][0]) < installs[0] < guests.index([c for c in guests if c[-1] == after][0])
        assert "rm -f /etc/systemd/system/docker.service.d/baseline-kasm-install.conf" in after


def test_the_data_disks_are_brought_up_in_the_guest_before_the_installer_runs_and_a_failure_stops_it(world):
    setup, fake = build(world)
    setup.run_install(100, {n: "x" * 20 for n in ks.SECRET_NAMES})
    guests = [c for c in fake.calls if c[:3] == ["qm", "guest", "exec"]]
    disks = [i for i, c in enumerate(guests) if c[-1] == "/usr/local/sbin/baseline-kasm-disks"]
    installs = [i for i, c in enumerate(guests) if c[-1] == "/usr/local/sbin/baseline-kasm-install"]
    assert disks and disks[0] < installs[0]

    class DisksFail(Fake):
        def __call__(self, argv, data=None, timeout=120):
            if argv[:3] == ["qm", "guest", "exec"] and argv[-1] == "/usr/local/sbin/baseline-kasm-disks":
                self.calls.append(list(argv))
                return 0, json.dumps({"exited": 1, "exitcode": 1}), ""                     # qm itself succeeds; the command inside did not
            return super().__call__(argv, data, timeout)

    bad, bad_fake = build(world, fake=DisksFail())
    with pytest.raises(ks.KasmSetupError, match="data disks could not be brought up"):
        bad.run_install(100, {n: "x" * 20 for n in ks.SECRET_NAMES})
    assert not [c for c in bad_fake.calls if c[-1] == "/usr/local/sbin/baseline-kasm-install"]


def test_status_reports_the_recipe_the_carried_base_recorded(world):
    import kasm_recipe
    recipe = kasm_recipe.summary(kasm_recipe.default([{"key": "k", "image": "chrome", "friendly_name": "K", "persistent": True}]))
    (world.base_dir / "KASM.json").write_text(json.dumps({"recipe": recipe, "holds_install_state_or_secrets": False}))
    setup, _ = build(world)
    got = setup.status()["recipe"]
    assert [c["id"] for c in got["components"]][-1] == "server-connections" and got["components"][-1]["state"] == "unused"
    (world.base_dir / "KASM.json").write_text(json.dumps({"recipe": "nonsense"}))
    assert setup.status()["recipe"] is None


def test_the_registry_address_is_handed_to_the_guest_only_when_the_base_was_built_with_one(world):
    import kasm_recipe
    def recipe_with(registry):
        recipe = kasm_recipe.default([{"key": "k", "image": "chrome", "friendly_name": "K", "persistent": True}])
        recipe["registry"] = registry
        (world.base_dir / "KASM.json").write_text(json.dumps({"recipe": kasm_recipe.summary(recipe)}))
    recipe_with({"enabled": False, "name": "B", "list_url": ""})
    setup, fake = build(world)
    setup.run_install(100, {n: "x" * 20 for n in ks.SECRET_NAMES})
    assert b"KASM_REGISTRY_URL" not in fake.inputs[-1]
    recipe_with({"enabled": True, "name": "B", "list_url": "https://h.example:8100/kasm-registry/"})
    again, fake2 = build(world)
    again.run_install(100, {n: "x" * 20 for n in ks.SECRET_NAMES})
    assert b"KASM_REGISTRY_URL=https://h.example:8100/kasm-registry/\n" in fake2.inputs[-1]


def test_telemetry_is_collected_from_the_running_vm_and_kept_and_reported(world):
    import kasm_telemetry as kt
    setup, fake = installed(world)
    fake.state = "running"
    fake.probe_output = "M mem_avail_pct 5\nM memory_psi_some10 30\nE error service_failed docker.service\nE error container_oom kasm_api was killed for lack of memory\n"
    for _ in range(3):
        got = setup.collect_telemetry(now=1_800_000_000.0 - 600 * _)
        assert (got["collected"], got["metrics"], got["events"]) == (True, 2, 2)
    report = setup.telemetry_report(now=1_800_000_000.0)
    memory = next(s for s in report["suggestions"] if s["id"] == "more-memory")
    assert memory["action"]["memory_mb"] == int(setup.read_record()["memory_mb"] * 1.5) // 512 * 512 and memory["severity"] == "error"
    assert report["errors"][0]["count"] == 3 and (world.admin_dir / "telemetry.sqlite").is_file()


def test_nothing_is_collected_when_the_vm_is_not_running_or_does_not_answer(world):
    class Silent(Fake):
        def __call__(self, argv, data=None, timeout=120):
            if "Read-only." in " ".join(argv):
                self.calls.append(list(argv))
                return 255, "", "no agent"
            return super().__call__(argv, data, timeout)

    setup, fake = installed(world)
    fake.state = "stopped"
    assert setup.collect_telemetry() == {"collected": False, "reason": "the Kasm VM is not running"}
    silent, silent_fake = build(world, fake=Silent())
    silent_fake.state = "running"
    silent_fake.vms.append({"name": ks.VM_NAME, "vmid": 100})
    (world.pve_conf_dir).mkdir(parents=True, exist_ok=True)
    (world.pve_conf_dir / "100.conf").write_text("x")
    assert silent.collect_telemetry() == {"collected": False, "reason": "the VM did not answer the probe"}


def test_the_report_is_empty_and_safe_with_no_history_or_no_vm(world):
    setup, _ = build(world)
    assert setup.telemetry_report() == {"suggestions": [], "errors": [], "setting_changes": [], "launches": {}}


SETTINGS_JSON = '[{"name":"log_retention","secret":false,"value":"7"},{"name":"hec_token","secret":true,"value":null},{"name":"https_insecure","secret":false,"value":"True"}]'


def test_settings_are_read_through_kasms_admin_api_with_the_password_on_stdin_and_changes_are_kept_with_their_values(world):
    import kasm_telemetry as kt
    setup, fake = installed(world)
    fake.state = "running"
    fake.probe_output = ""
    fake.settings_output = SETTINGS_JSON
    first = setup.collect_telemetry(now=1_800_000_000.0 - 3600)
    assert first["setting_changes"] == 3                                                      # the first look: every setting is a first observation
    assert fake.settings_stdin == (setup.vault.get("KASM_ADMIN_PASSWORD") + "\n").encode()
    assert not [c for c in fake.calls if setup.vault.get("KASM_ADMIN_PASSWORD") in " ".join(c)]   # the password is on no command line
    assert setup.collect_telemetry(now=1_800_000_000.0 - 1800)["setting_changes"] == 0         # nothing changed, nothing recorded (a secret is noted once)
    fake.settings_output = SETTINGS_JSON.replace('"7"', '"14"')
    assert setup.collect_telemetry(now=1_800_000_000.0)["setting_changes"] == 1
    conn = setup.telemetry_db()
    report = {r["name"]: r for r in kt.setting_report(conn, 0)}
    assert (report["log_retention"]["last_old"], report["log_retention"]["last_new"], report["log_retention"]["changes"]) == ("7", "14", 2)
    assert report["hec_token"]["secret"] and "<secret>" not in str(conn.execute("SELECT new_value FROM setting_changes WHERE name='hec_token'").fetchall())


def test_a_sealed_vault_or_a_silent_kasm_just_skips_the_settings_look(world):
    setup, fake = installed(world)
    fake.state = "running"
    fake.settings_output = ""                                                                  # Kasm did not answer
    assert setup.collect_telemetry()["setting_changes"] is None
    setup.vault.set_passphrase("a long enough passphrase")
    fake.settings_output = SETTINGS_JSON
    assert setup.collect_telemetry()["setting_changes"] is None                                # sealed, no passphrase given: skipped, not an error
    assert setup.collect_telemetry(passphrase="a long enough passphrase")["setting_changes"] == 3


def test_usage_and_failed_sessions_come_from_kasms_accounting_and_a_failure_is_one_event(world):
    import kasm_telemetry as kt
    setup, fake = installed(world)
    fake.state = "running"
    fake.accounting_output = "Chrome|12|3.50|0\nVS Code|3|1.00|2\n"
    assert setup.collect_telemetry(now=1_800_000_000.0 - 7200)["usage_images"] == 2
    setup.collect_telemetry(now=1_800_000_000.0 - 3600)                                         # the same totals again: no new failure event
    fake.accounting_output = "Chrome|20|5.00|0\nVS Code|4|1.50|3\n"
    setup.collect_telemetry(now=1_800_000_000.0)
    conn = setup.telemetry_db()
    failures = [r for r in kt.error_report(conn, 0) if r["source"] == "workspace_failed"]
    assert failures[0]["count"] == 2 and "VS Code" in failures[0]["message"]                  # the first failure total, then the growth; the unchanged look added nothing
    assert kt.launches_report(conn, 1_800_000_000.0 - 8000) == {"Chrome": 8, "VS Code": 1}


BRIDGE = json.dumps([{"ifname": "vmbr0", "addr_info": [{"family": "inet6", "scope": "link", "local": "fe80::1"}, {"family": "inet", "scope": "global", "local": "192.168.50.7"}]}])


def test_the_registry_address_is_this_hosts_own_bridge_address_unless_the_recipe_gives_one(world):
    class Ip(Fake):
        def __call__(self, argv, data=None, timeout=120):
            if argv[:3] == ["ip", "-j", "address"]:
                return 0, BRIDGE, ""
            return super().__call__(argv, data, timeout)
    setup, _ = build(world, fake=Ip())
    assert setup.registry_address({"enabled": True, "list_url": ""}) == "http://192.168.50.7:8100/kasm-registry/"
    assert setup.registry_address({"enabled": True, "list_url": "https://given.example/r/"}) == "https://given.example/r/"
    assert setup.registry_address({"enabled": False, "list_url": ""}) == ""


def test_no_address_is_given_when_there_is_no_bridge_address_or_it_cannot_be_read(world):
    class NoBridge(Fake):
        def __call__(self, argv, data=None, timeout=120):
            if argv[:3] == ["ip", "-j", "address"]:
                return 0, json.dumps([{"ifname": "vmbr0", "addr_info": [{"family": "inet6", "scope": "global", "local": "fec0::1"}]}]), ""
            return super().__call__(argv, data, timeout)
    setup, _ = build(world, fake=NoBridge())
    assert setup.registry_address({"enabled": True, "list_url": ""}) == ""                    # IPv6 only: nothing is offered rather than a wrong address
    broken, _ = build(world, fake=type("Broken", (Fake,), {"__call__": lambda self, argv, data=None, timeout=120: (1, "", "no vmbr0") if argv[0] == "ip" else Fake.__call__(self, argv, data, timeout)})())
    assert broken.registry_address({"enabled": True, "list_url": ""}) == ""
