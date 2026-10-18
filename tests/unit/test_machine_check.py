"""The boot-time machine check: fingerprint fallback, readiness, executors and the full pass. Real files stand in for sysfs and the mounts."""
import json

import pytest

import identifiers as idn
import machine_check as mk
import machine_context as mc
import references as ref

LANE = "4af8c95a-1c9b-437a-a306-c53855d4077f"
SERIAL = "SYNTHDRIVEA00001"


@pytest.fixture
def host(tmp_path, monkeypatch):
    h = idn.host_id(LANE, SERIAL)
    idn.register_host(h, serial=SERIAL)
    path = tmp_path / "host-id"
    path.write_text(h + "\n")
    monkeypatch.setattr(ref, "HOST_ID_FILE", path)
    return h


def machine(tmp_path, name, *, uuid=None, macs=("52:54:00:12:34:56",)):
    root = tmp_path / name
    (root / "sys/class/dmi/id").mkdir(parents=True)
    if uuid:
        (root / "sys/class/dmi/id/product_uuid").write_text(uuid + "\n")
    for i, mac in enumerate(macs):
        nic = root / "sys/class/net" / f"enp{i}s0"
        (nic / "device").mkdir(parents=True)
        (nic / "address").write_text(mac + "\n")
    (root / "sys/class/net/lo").mkdir(parents=True)
    (root / "sys/class/net/vmbr0/bridge").mkdir(parents=True)
    (root / "sys/class/net/vmbr0/address").write_text("52:54:00:12:34:56\n")
    (root / "sys/class/net/wlp1s0/wireless").mkdir(parents=True)
    (root / "sys/class/net/wlp1s0/device").mkdir()
    (root / "proc").mkdir(exist_ok=True)
    (root / "proc/cpuinfo").write_text("model name\t: Test CPU\n")
    return mc.file_reader(str(root))


def test_with_no_firmware_identity_the_wired_nic_addresses_are_the_identity_and_bridges_and_wireless_are_ignored(tmp_path):
    fp = mc.read_fingerprint(machine(tmp_path, "vm", macs=("52:54:00:12:34:56", "52:54:00:12:34:57")))
    assert fp["nic_macs"] == "52:54:00:12:34:56,52:54:00:12:34:57" and "nics" not in fp and "system_uuid" not in fp


def test_with_a_firmware_identity_the_nics_are_only_parts_so_swapping_one_is_a_change_not_a_new_machine(tmp_path, host):
    uid = "11111111-2222-4333-8444-555555555555"
    first = mc.observe(host, mc.read_fingerprint(machine(tmp_path, "a", uuid=uid, macs=("02:00:5e:00:00:00",))))
    assert first["state"] == "first_machine"
    swapped = mc.observe(host, mc.read_fingerprint(machine(tmp_path, "b", uuid=uid, macs=("02:00:5e:00:00:01",))))
    assert swapped["state"] == "changed" and swapped["differs"] == ["nics"]


def test_a_machine_with_no_firmware_identity_is_recorded_by_its_nics_instead_of_staying_unreadable(tmp_path, host):
    assert mc.observe(host, mc.read_fingerprint(machine(tmp_path, "vm")))["state"] == "first_machine"
    assert mc.observe(host, mc.read_fingerprint(machine(tmp_path, "vm2")))["state"] == "known"
    assert mc.observe(host, mc.read_fingerprint(machine(tmp_path, "other", macs=("02:00:5e:00:00:02",))))["state"] == "new_machine"


def test_readiness_stages_follow_what_is_actually_up(tmp_path):
    env = tmp_path / "harness.env"
    assert mk.probe_stages(mounted=lambda p: False, unit_active=lambda u: False, connect=lambda: False, harness_env=env) == set()
    assert mk.probe_stages(mounted=lambda p: True, unit_active=lambda u: False, connect=lambda: False, harness_env=env) == {"substrate"}
    env.write_text("TOKEN=x\n")
    everything = mk.probe_stages(mounted=lambda p: True, unit_active=lambda u: True, connect=lambda: True, harness_env=env)
    assert everything == set(mc.STAGES)


def test_a_new_machine_runs_its_deterministic_checks_defers_what_fails_and_leaves_helper_work_queued(tmp_path, host):
    mk.run_once(read=machine(tmp_path, "home", uuid="11111111-2222-4333-8444-555555555555"), stages={"substrate"},
                collect=lambda: ({}, None), mounted=lambda p: True, state_dir=tmp_path / "m", cache_root=tmp_path / "nocache")
    unmounted = lambda p: p != "/mnt/APPDATA_ADMIN"
    result = mk.run_once(read=machine(tmp_path, "moved", uuid="99999999-2222-4333-8444-555555555555"), stages={"substrate"},
                         collect=lambda: ({"cpu": "x"}, None), mounted=unmounted, state_dir=tmp_path / "m", cache_root=tmp_path / "nocache")
    assert result["state"] == "new_machine"
    outcomes = {r["task"].split(":")[1]: r["outcome"] for r in result["ran"]}
    assert outcomes["discover-hardware"] == "done" and outcomes["check-installer-cache"] == "not_needed"
    assert outcomes["check-user-data"] == "defer" or outcomes["check-user-data"] == "done"
    assert "rebuild-vm-config" not in outcomes and "resolve-incompatibilities" not in outcomes
    assert (tmp_path / "m").is_dir() and list((tmp_path / "m").glob("*.hardware.json"))
    pending = {t.split(":")[1] for t, _ in mc.due(set(mc.STAGES))}
    assert {"rebuild-vm-config", "resolve-incompatibilities"} <= pending


def test_a_failed_check_is_deferred_with_its_reason_not_raised_and_not_forgotten(tmp_path, host):
    mk.run_once(read=machine(tmp_path, "home", uuid="11111111-2222-4333-8444-555555555555"), stages={"substrate"},
                collect=lambda: (None, "inxi missing"), mounted=lambda p: True, state_dir=tmp_path / "m", cache_root=tmp_path / "c")
    result = mk.run_once(read=machine(tmp_path, "moved", uuid="99999999-2222-4333-8444-555555555555"), stages={"substrate"},
                         collect=lambda: (None, "inxi missing"), mounted=lambda p: True, state_dir=tmp_path / "m", cache_root=tmp_path / "c")
    hw = next(r for r in result["ran"] if r["task"].endswith("discover-hardware"))
    assert hw["outcome"] == "defer" and "inxi missing" in hw["detail"]
    entry = next(a for t, a in mc.due(set(mc.STAGES)) if t.endswith("discover-hardware"))
    assert entry["needs_helper"] and "inxi missing" in entry["detail"]


def test_without_a_host_identifier_the_check_does_nothing_and_does_not_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(ref, "HOST_ID_FILE", tmp_path / "absent")
    assert mk.run_once(stages=set()) == {"state": "no_host_identifier", "ran": []}
