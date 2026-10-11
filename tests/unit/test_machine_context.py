"""DR256: a mismatch is a state with behaviours, never a failure. Real files under a temp root stand in for sysfs/procfs."""
import pytest

import identifiers as idn
import machine_context as mc

LANE = "4af8c95a-1c9b-437a-a306-c53855d4077f"
SERIAL = "FD01N6557110C271B"


@pytest.fixture
def host():
    h = idn.host_id(LANE, SERIAL)
    idn.register_host(h, serial=SERIAL)
    return h


def machine(tmp_path, name, *, uuid, board="B550-1", cpu="Ryzen 9 7900X", mem_kb=100 * 1024 * 1024):
    root = tmp_path / name
    dmi = root / "sys/class/dmi/id"
    dmi.mkdir(parents=True)
    (dmi / "product_uuid").write_text(uuid + "\n")
    (dmi / "board_serial").write_text(board + "\n")
    (root / "proc").mkdir()
    (root / "proc/cpuinfo").write_text(f"processor : 0\nmodel name\t: {cpu}\n")
    (root / "proc/meminfo").write_text(f"MemTotal:       {mem_kb} kB\n")
    return mc.read_fingerprint(mc.file_reader(str(root)))


def test_a_fingerprint_is_read_from_real_files_and_placeholder_values_are_ignored(tmp_path):
    fp = machine(tmp_path, "a", uuid="11111111-2222-4333-8444-555555555555", board="To be filled by O.E.M.")
    assert fp["system_uuid"] == "11111111-2222-4333-8444-555555555555" and "board_serial" not in fp
    assert fp["cpu_model"] == "Ryzen 9 7900X" and fp["memory_gib"] == "100"


def test_the_first_machine_is_recorded_as_the_installer_host_with_nothing_to_do(tmp_path, host):
    result = mc.observe(host, machine(tmp_path, "a", uuid="11111111-2222-4333-8444-555555555555"))
    assert result["state"] == "first_machine" and result["tasks"] == []
    assert list(mc.load_profiles()) == [result["profile"]]


def test_the_same_machine_again_is_known_and_a_changed_part_is_noticed_not_refused(tmp_path, host):
    uid = "11111111-2222-4333-8444-555555555555"
    first = mc.observe(host, machine(tmp_path, "a", uuid=uid))
    assert mc.observe(host, machine(tmp_path, "a2", uuid=uid))["state"] == "known"
    changed = mc.observe(host, machine(tmp_path, "a3", uuid=uid, mem_kb=50 * 1024 * 1024))
    assert changed["state"] == "changed" and changed["profile"] == first["profile"] and changed["differs"] == ["memory_gib"]
    assert [t.split(":")[1] for t in changed["tasks"]] == ["recheck-changed-parts"]


def test_a_new_machine_gets_its_own_profile_and_a_plan_instead_of_an_error(tmp_path, host):
    first = mc.observe(host, machine(tmp_path, "a", uuid="11111111-2222-4333-8444-555555555555"))
    moved = mc.observe(host, machine(tmp_path, "b", uuid="99999999-2222-4333-8444-555555555555", board="X570-9"))
    assert moved["state"] == "new_machine" and moved["profile"] != first["profile"]
    assert len(mc.load_profiles()) == 2
    kinds = [t.split(":")[1] for t in moved["tasks"]]
    assert kinds[:4] == ["discover-hardware", "check-installer-cache", "check-appdata", "check-user-data"]
    assert "resolve-incompatibilities" in kinds
    assert mc.observe(host, machine(tmp_path, "b2", uuid="99999999-2222-4333-8444-555555555555", board="X570-9"))["state"] == "known"


def test_an_unreadable_fingerprint_is_a_state_and_never_an_exception(tmp_path, host):
    result = mc.observe(host, mc.read_fingerprint(mc.file_reader(str(tmp_path / "nothing"))))
    assert result["state"] == "unreadable" and mc.load_profiles() == {}


def test_deterministic_work_is_due_once_the_substrate_is_up_but_helper_work_waits_for_the_ai(tmp_path, host):
    mc.observe(host, machine(tmp_path, "a", uuid="11111111-2222-4333-8444-555555555555"))
    mc.observe(host, machine(tmp_path, "b", uuid="99999999-2222-4333-8444-555555555555", board="X570-9"))
    kinds = lambda ready: [t.split(":")[1] for t, _ in mc.due(ready)]
    assert kinds(set()) == []
    assert kinds({"substrate"}) == ["discover-hardware", "check-installer-cache", "check-appdata", "check-user-data"]
    assert "rebuild-vm-config" not in kinds({"substrate", "gui", "browser", "internet"})
    assert "rebuild-vm-config" in kinds(set(mc.STAGES))


def test_work_that_cannot_be_settled_deterministically_is_deferred_to_the_helper_and_done_work_leaves_the_queue(tmp_path, host):
    mc.observe(host, machine(tmp_path, "a", uuid="11111111-2222-4333-8444-555555555555"))
    moved = mc.observe(host, machine(tmp_path, "b", uuid="99999999-2222-4333-8444-555555555555", board="X570-9"))
    appdata = next(t for t in moved["tasks"] if t.endswith("check-appdata"))
    mc.defer(appdata, "app data volume uses a driver this machine lacks")
    assert appdata not in [t for t, _ in mc.due({"substrate"})] and appdata in [t for t, _ in mc.due(set(mc.STAGES))]
    mc.complete(appdata)
    assert appdata not in [t for t, _ in mc.due(set(mc.STAGES))]
    with pytest.raises(mc.ContextError):
        mc.complete("nope:nothing")
