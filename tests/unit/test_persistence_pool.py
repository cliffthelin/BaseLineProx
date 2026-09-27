"""Unit tests for persistence_pool.py - the real-hardware
LVM-thin persistence pool setup. Track A2 did this once, for real, via
ad hoc manual commands narrated only in prose (docs/SESSION_HANDOFF.md)
with no reusable code left behind - this module is a NEW
reconstruction of that intended procedure, not a recovery of the
exact original commands (which are lost/unconfirmed - see
docs/INSTALL.md's own note on this). No real lvm/pvesm is ever invoked
- the FakeRunner records every argv and returns scripted results."""
from fake_runner import FakeProc, FakeRunner

import persistence_pool as pp


VALIDATED = {"path": "/dev/sdb", "serial": "MD89N41071210AP4E", "size_bytes": 512110190592}


# -- pure argv builders ---------------------------------------------------

def test_list_volume_groups_argv():
    assert pp.list_volume_groups_argv() == ["vgs", "--noheadings", "-o", "vg_name,vg_uuid"]


def test_deactivate_vg_by_uuid_argv_never_addresses_by_name_alone():
    argv = pp.deactivate_vg_by_uuid_argv("abc-123-uuid")
    assert argv == ["vgchange", "-an", "--select", "vg_uuid=abc-123-uuid"]
    assert "pve" not in argv  # never a hardcoded/guessed VG name


def test_create_thin_pool_argvs_never_accepts_a_bare_path():
    # Only the validated dict's own resolved path is used - never a
    # string a caller could pass unchecked.
    argvs = pp.create_thin_pool_argvs(VALIDATED)
    assert argvs[0] == ["pvcreate", "/dev/sdb"]
    assert argvs[1] == ["vgcreate", pp.DEFAULT_VG_NAME, "/dev/sdb"]
    assert argvs[2] == ["lvcreate", "-T", f"{pp.DEFAULT_VG_NAME}/{pp.DEFAULT_POOL_NAME}", "-l", "100%FREE"]


def test_create_thin_pool_argvs_with_custom_names():
    argvs = pp.create_thin_pool_argvs(VALIDATED, vg_name="myvg", pool_name="mypool")
    assert argvs[1] == ["vgcreate", "myvg", "/dev/sdb"]
    assert argvs[2] == ["lvcreate", "-T", "myvg/mypool", "-l", "100%FREE"]


def test_register_with_proxmox_argv():
    assert pp.register_with_proxmox_argv() == [
        "pvesm", "add", "lvmthin", pp.DEFAULT_STORAGE_ID,
        "--vgname", pp.DEFAULT_VG_NAME, "--thinpool", pp.DEFAULT_POOL_NAME,
    ]


def test_register_with_proxmox_argv_with_custom_storage_id():
    argv = pp.register_with_proxmox_argv(storage_id="other-persist")
    assert argv[3] == "other-persist"


# -- parsing real vgs output ----------------------------------------------

def test_parse_volume_groups_output():
    text = "  pve   AbCd-1234-uuid-one  \n  pve   WxYz-5678-uuid-two  \n"
    groups = pp.parse_volume_groups(text)
    assert groups == [("pve", "AbCd-1234-uuid-one"), ("pve", "WxYz-5678-uuid-two")]


def test_parse_volume_groups_output_empty():
    assert pp.parse_volume_groups("") == []


def test_find_stale_vg_uuids_by_name_excludes_the_keep_uuid():
    groups = [("pve", "uuid-old"), ("pve", "uuid-new"), ("data", "uuid-other")]
    stale = pp.find_stale_vg_uuids(groups, name="pve", keep_uuid="uuid-new")
    assert stale == ["uuid-old"]


def test_find_stale_vg_uuids_none_when_only_one_matches():
    groups = [("pve", "uuid-new"), ("data", "uuid-other")]
    assert pp.find_stale_vg_uuids(groups, name="pve", keep_uuid="uuid-new") == []


# -- Runner-executed operations --------------------------------------------

def test_deactivate_stale_vgs_deactivates_every_stale_uuid_and_none_else():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["vgs", "--noheadings"],
         FakeProc(0, "  pve   uuid-old  \n  pve   uuid-new  \n", "")),
    ])
    result = pp.deactivate_stale_vgs(runner, name="pve", keep_uuid="uuid-new")
    assert result.ok is True
    assert runner.calls[-1] == ["vgchange", "-an", "--select", "vg_uuid=uuid-old"]
    # never deactivates the one we're keeping
    assert ["vgchange", "-an", "--select", "vg_uuid=uuid-new"] not in runner.calls


def test_deactivate_stale_vgs_reports_success_with_nothing_stale():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["vgs", "--noheadings"], FakeProc(0, "  pve   uuid-new  \n", "")),
    ])
    result = pp.deactivate_stale_vgs(runner, name="pve", keep_uuid="uuid-new")
    assert result.ok is True
    assert "nothing stale" in result.detail.lower()


def test_create_thin_pool_stops_at_the_first_failing_command():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["vgcreate"], FakeProc(1, "", "Device /dev/sdb excluded")),
    ])
    result = pp.create_thin_pool(runner, VALIDATED)
    assert result.ok is False
    assert "vgcreate" in result.detail
    # lvcreate must never have been attempted after vgcreate failed
    assert not any(c[0] == "lvcreate" for c in runner.calls)


def test_create_thin_pool_reports_success_after_all_three_commands():
    runner = FakeRunner()
    result = pp.create_thin_pool(runner, VALIDATED)
    assert result.ok is True
    assert [c[0] for c in runner.calls] == ["pvcreate", "vgcreate", "lvcreate"]


def test_register_with_proxmox_reports_success():
    runner = FakeRunner()
    result = pp.register_with_proxmox(runner)
    assert result.ok is True
    assert runner.calls[0][:3] == ["pvesm", "add", "lvmthin"]


def test_register_with_proxmox_reports_the_real_failure_detail():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["pvesm", "add"], FakeProc(1, "", "storage ID already in use")),
    ])
    result = pp.register_with_proxmox(runner)
    assert result.ok is False
    assert "already in use" in result.detail
