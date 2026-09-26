"""Unit tests for pct_provision.py (Track A6, LXC half) - the
complementary primitive to vm_provision.py for lightweight, always-on
Linux utility services. No real pct/pveam is ever invoked - the
FakeRunner records every argv and returns scripted results."""
from fake_runner import FakeProc, FakeRunner

import pct_provision as ctp


# -- pure argv builders ------------------------------------------------

def test_create_ct_argv_shape():
    argv = ctp.create_ct_argv(301, "local:vztmpl/debian-12-standard.tar.zst", hostname="util-1")
    assert argv == [
        "pct", "create", "301", "local:vztmpl/debian-12-standard.tar.zst",
        "--hostname", "util-1",
        "--memory", "512",
        "--cores", "1",
        "--rootfs", "local-lvm:4",
        "--net0", "name=eth0,bridge=vmbr0,ip=dhcp",
        "--unprivileged", "1",
    ]


def test_create_ct_argv_privileged_variant():
    argv = ctp.create_ct_argv(301, "tmpl", hostname="util-1", unprivileged=False)
    assert argv[-2:] == ["--unprivileged", "0"]


def test_start_stop_destroy_ct_argv_shapes():
    assert ctp.start_ct_argv(301) == ["pct", "start", "301"]
    assert ctp.stop_ct_argv(301) == ["pct", "stop", "301"]
    assert ctp.destroy_ct_argv(301) == ["pct", "destroy", "301", "--purge"]
    assert ctp.destroy_ct_argv(301, purge=False) == ["pct", "destroy", "301"]


def test_list_available_templates_argv():
    assert ctp.list_available_templates_argv() == ["pveam", "available"]


# -- VMID namespace is shared with vm_provision, not duplicated --------

def test_next_free_vmid_is_reused_from_vm_provision():
    import vm_provision as vp
    assert ctp.next_free_vmid_argv is vp.next_free_vmid_argv
    assert ctp.next_free_vmid is vp.next_free_vmid


# -- Runner-executed operations -----------------------------------------

def test_create_ct_reports_success():
    runner = FakeRunner()
    result = ctp.create_ct(runner, 301, "tmpl", hostname="util-1")
    assert result.ok is True
    assert runner.calls[0][:4] == ["pct", "create", "301", "tmpl"]


def test_create_ct_reports_the_real_failure_detail():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["pct", "create"], FakeProc(1, "", "CT 301 already exists")),
    ])
    result = ctp.create_ct(runner, 301, "tmpl", hostname="util-1")
    assert result.ok is False
    assert "already exists" in result.detail


def test_start_stop_destroy_ct_call_pct_directly():
    runner = FakeRunner()
    ctp.start_ct(runner, 301)
    ctp.stop_ct(runner, 301)
    ctp.destroy_ct(runner, 301)
    assert runner.calls == [
        ["pct", "start", "301"],
        ["pct", "stop", "301"],
        ["pct", "destroy", "301", "--purge"],
    ]


def test_list_available_templates_parses_pveam_output():
    runner = FakeRunner(command_responses=[
        (lambda a: a == ["pveam", "available"], FakeProc(
            0,
            "system          debian-12-standard_12.7-1_amd64.tar.zst\n"
            "system          ubuntu-22.04-standard_22.04-1_amd64.tar.zst\n",
            "",
        )),
    ])
    templates = ctp.list_available_templates(runner)
    assert templates == [
        "debian-12-standard_12.7-1_amd64.tar.zst",
        "ubuntu-22.04-standard_22.04-1_amd64.tar.zst",
    ]


def test_list_available_templates_raises_on_pveam_failure():
    runner = FakeRunner(command_responses=[
        (lambda a: a == ["pveam", "available"], FakeProc(1, "", "no such storage")),
    ])
    try:
        ctp.list_available_templates(runner)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "no such storage" in str(exc)
