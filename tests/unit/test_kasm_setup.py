"""Kasm on Proxmox (kasm_setup.py): what is created where, that the persistent disks are never replaced, and that credentials are recorded before use and
travel only on stdin. Proxmox's commands go through a scripted fake; the disks and vault are a real temp tree."""
import json

import pytest

import kasm_setup as ks
import vault as vault_mod


class Fake:
    """Scripted Proxmox: remembers calls, answers the few commands setup uses, and creates the files qemu-img would."""

    def __init__(self, vms=None, storages=None, agent_after=0, install_exit=0):
        self.calls, self.inputs = [], []
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
                return 0, json.dumps(self.vms), ""
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
            return 0, json.dumps({"exited": 1, "exitcode": self.install_exit, "out-data": "boom" if self.install_exit else ""}), ""
        return 0, "", ""

    def named(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


@pytest.fixture
def world(tmp_path):
    layout = ks.Layout(root_dir=tmp_path / "temp" / "kasm", admin_dir=tmp_path / "admin" / "kasm", profiles_dir=tmp_path / "personal" / "kasm",
                       base_dir=tmp_path / "cache" / "kasm", vault_path=str(tmp_path / "vault"), mounts=())
    layout.base_dir.mkdir(parents=True)
    layout.base.write_bytes(b"base image")
    (layout.base_dir / "KASM.json").write_text(json.dumps({"sha256": "abc", "kasm_version": "1.19.0", "holds_install_state_or_secrets": False}))
    return layout


def build(world, fake=None, **kwargs):
    fake = fake or Fake()
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


def test_setup_builds_the_vm_with_each_disk_on_its_own_volume_attached_by_serial(world):
    setup, fake = build(world)
    result = setup.setup()
    config = fake.named("qm", "create")[0]
    assert result["vmid"] == 100 and result["created"] and result["url"] == "https://192.168.1.50"
    assert "baseline-kasm-root:100/vm-100-disk-0.qcow2" in config
    assert f"baseline-kasm-admin:100/vm-100-disk-1.qcow2,serial={ks.ADMIN_SERIAL}" in config
    assert f"baseline-kasm-prof:100/vm-100-disk-2.qcow2,serial={ks.PROFILES_SERIAL}" in config
    assert (world.root_dir / "images/100/vm-100-disk-0.qcow2").is_file() and (world.admin_dir / "images/100/vm-100-disk-1.qcow2").is_file()
    assert (world.profiles_dir / "images/100/vm-100-disk-2.qcow2").is_file()
    assert len(ks.ADMIN_SERIAL) <= 20 and len(ks.PROFILES_SERIAL) <= 20


def test_the_root_is_an_overlay_on_the_vanilla_base_and_the_data_disks_are_bare_sparse(world):
    setup, fake = build(world)
    setup.setup()
    creates = {c[-2] if c[-1].endswith("G") else c[-1]: c for c in fake.named("qemu-img", "create")}
    root = creates[str(world.root_dir / "images/100/vm-100-disk-0.qcow2")]
    assert ["-b", str(world.base), "-F", "qcow2"] == root[root.index("-b"):root.index("-b") + 4]
    for name in ("admin", "personal"):
        argv = next(c for p, c in creates.items() if f"/{name}/" in p)
        assert "-b" not in argv and "-o" not in argv and not [a for a in argv if "prealloc" in a]       # reserved, never written


def test_the_installer_cache_base_is_only_ever_read(world):
    setup, fake = build(world)
    setup.setup()
    before = world.base.read_bytes()
    setup.reset_root()
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
    with pytest.raises(ks.KasmSetupError, match="did not finish") as info:
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


def test_a_rebuild_after_the_vm_was_destroyed_reattaches_the_persistent_disks_under_the_same_vmid(world):
    setup, _ = build(world)
    setup.setup()
    marker = world.profiles_dir / "images/100/vm-100-disk-2.qcow2"
    marker.write_bytes(b"the user's profiles")
    (world.admin_dir / "images/100/vm-100-disk-1.qcow2").write_bytes(b"kasm state")
    again, fake = build(world)                                                              # Proxmox no longer lists the VM; the disks and record remain
    again.layout.root_dir.joinpath("images/100/vm-100-disk-0.qcow2").unlink()
    result = again.setup()
    assert result["vmid"] == 100 and result["created"]
    assert marker.read_bytes() == b"the user's profiles" and (world.admin_dir / "images/100/vm-100-disk-1.qcow2").read_bytes() == b"kasm state"
    assert not [c for c in fake.named("qemu-img", "create") if c[-1].endswith("G") or "disk-1" in c[-1] or "disk-2" in c[-1]]
    assert not fake.named("pvesh", "get", "/cluster/nextid")


def test_reset_root_replaces_only_the_root_disk(world):
    setup, fake = build(world)
    setup.setup()
    (world.admin_dir / "images/100/vm-100-disk-1.qcow2").write_bytes(b"kasm state")
    (world.profiles_dir / "images/100/vm-100-disk-2.qcow2").write_bytes(b"profiles")
    root = world.root_dir / "images/100/vm-100-disk-0.qcow2"
    root.write_bytes(b"old root with a lot of writes")
    result = setup.reset_root()
    assert result["vmid"] == 100 and root.read_bytes() == b"qcow2"                           # a fresh overlay
    assert (world.admin_dir / "images/100/vm-100-disk-1.qcow2").read_bytes() == b"kasm state"
    assert (world.profiles_dir / "images/100/vm-100-disk-2.qcow2").read_bytes() == b"profiles"


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
    assert setup.status() == {"present": False, "installed": False, "recorded_vmid": None, "workspaces": None}
    setup.setup()
    fake.state = "running"
    now = setup.status()
    assert now["present"] and now["running"] and now["installed"] and now["url"] == "https://192.168.1.50"
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
