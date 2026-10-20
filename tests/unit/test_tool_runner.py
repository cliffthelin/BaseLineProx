"""Each diagnostic tool has its own address and runs from the browser: only fixed commands, and the few values a person picks are checked against what this host
really has (a drive from the scan, a network card from /sys/class/net, a plain host name)."""
import tool_runner as tr


class Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def fake(calls, out="ok\n", rc=0):
    def run(argv, **kw):
        calls.append((argv, kw))
        return Proc(rc, out)
    return run


def test_every_tool_has_a_page_and_at_least_one_action():
    assert set(tr.TOOLS) == {"lm-sensors", "nvme-cli", "smartmontools", "iperf3", "ethtool"}
    for name, tool in tr.TOOLS.items():
        assert tool["actions"], name


def test_active_iperf_client_run_is_post_only():
    assert tr.TOOLS["iperf3"]["actions"]["test"]["post"] is True


def test_a_fixed_action_runs_its_own_command_with_a_time_limit():
    calls = []
    result = tr.run("lm-sensors", "readings", "", runner=fake(calls, "temp1: 41C\n"))
    assert calls[0][0] == ["sensors"] and calls[0][1]["timeout"] <= 120
    assert result["ok"] and "41C" in result["output"]


def test_an_unknown_tool_or_action_is_refused_and_nothing_runs():
    calls = []
    assert not tr.run("rm", "readings", "", runner=fake(calls))["ok"]
    assert not tr.run("lm-sensors", "format", "", runner=fake(calls))["ok"]
    assert calls == []


def test_a_drive_must_come_from_the_hosts_own_scan():
    calls = []
    scan = "/dev/sda -d scsi # /dev/sda, SCSI device\n/dev/nvme0 -d nvme # /dev/nvme0, NVMe device\n"
    def runner(argv, **kw):
        calls.append(argv)
        return Proc(0, scan if argv[:2] == ["smartctl", "--scan"] else "PASSED\n")
    assert tr.run("smartmontools", "health", "/dev/nvme0", runner=runner)["ok"]
    assert calls[-1] == ["smartctl", "-H", "/dev/nvme0"]
    bad = tr.run("smartmontools", "health", "/dev/sda; reboot", runner=runner)
    assert not bad["ok"] and calls[-1] != ["smartctl", "-H", "/dev/sda; reboot"]


def test_a_network_card_must_exist_here(tmp_path):
    (tmp_path / "enp3s0").mkdir()
    calls = []
    assert tr.run("ethtool", "link", "enp3s0", runner=fake(calls), net_dir=str(tmp_path))["ok"]
    assert calls[0][0] == ["ethtool", "enp3s0"]
    assert not tr.run("ethtool", "link", "../etc", runner=fake(calls), net_dir=str(tmp_path))["ok"]


def test_iperf_target_is_a_plain_host_name_or_address():
    calls = []
    assert tr.run("iperf3", "test", "192.168.1.20", runner=fake(calls))["ok"]
    assert calls[0][0][:3] == ["iperf3", "-c", "192.168.1.20"]
    for bad in ("", "a b", "x;y", "-s", "$(id)"):
        assert not tr.run("iperf3", "test", bad, runner=fake(calls))["ok"]


def test_choices_lists_what_a_person_can_pick(tmp_path):
    (tmp_path / "enp3s0").mkdir(); (tmp_path / "lo").mkdir()
    assert tr.choices("ethtool", "link", net_dir=str(tmp_path)) == ["enp3s0"]


def test_a_missing_tool_is_reported_not_crashed():
    def runner(argv, **kw):
        raise FileNotFoundError(argv[0])
    result = tr.run("lm-sensors", "readings", "", runner=runner)
    assert not result["ok"] and "not installed" in result["output"]


def test_page_has_each_action_and_escapes_output():
    page = tr.render("lm-sensors", {"ok": True, "output": "<script>x</script>", "action": "readings"}).decode()
    assert "<script>x</script>" not in page and "&lt;script&gt;" in page
    assert "/tools/lm-sensors" in page
