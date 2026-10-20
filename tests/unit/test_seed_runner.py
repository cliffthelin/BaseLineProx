"""The first-boot seed runner for bases that have no cloud-init (Bazzite, Omarchy): the same user-data the other systems' cloud-init reads, applied by a small stdlib-only script."""
import json

import pytest

import seed_runner as sr
import prebuilt_environment as pe


class Cmds:
    def __init__(self, groups=("wheel", "users"), existing_users=()):
        self.calls, self.groups, self.users = [], set(groups), set(existing_users)

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[:2] == ["getent", "group"]:
            return (0 if argv[2] in self.groups else 2), "", ""
        if argv[:2] == ["getent", "passwd"]:
            return (0 if argv[2] in self.users else 2), "", ""
        return 0, "", ""


def seed(os_id="bazzite", owner="cliff", initialize_home=True):
    text = pe.cloud_config(os_id, owner=owner, initialize_home=initialize_home, hostname="work")
    return text, json.dumps({"instance-id": "abc123", "local-hostname": "work"})      # exactly what write_seed puts on the seed disk


def run(tmp_path, cmds=None, os_id="bazzite", state=None, **kw):
    cmds = cmds or Cmds()
    user_data, meta = seed(os_id, **kw)
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    result = sr.apply(user_data, meta, run=cmds, root=root, state_dir=state or tmp_path / "state")
    return result, cmds, root


def test_user_data_is_parsed_and_the_instance_id_is_read():
    user_data, meta = seed()
    assert sr.parse_user_data(user_data)["users"][0]["name"] == "cliff"
    assert sr.instance_id(meta) == "abc123" and sr.instance_id("instance-id: abc123\nlocal-hostname: work\n") == "abc123"
    with pytest.raises(sr.SeedError):
        sr.parse_user_data("not a cloud config")


def test_the_owner_is_made_with_the_fixed_uid_no_password_and_only_the_groups_the_system_has(tmp_path):
    result, cmds, root = run(tmp_path)
    useradd = next(c for c in cmds.calls if c[0] == "useradd")
    assert useradd[useradd.index("-u") + 1] == "1100" and "cliff" in useradd
    assert "wheel" in useradd[useradd.index("-G") + 1] and "sudo" not in useradd[useradd.index("-G") + 1]      # Fedora has wheel, not sudo
    assert ["passwd", "-l", "cliff"] in cmds.calls                                                              # no password exists
    sudoers = (root / "etc/sudoers.d/90-baseline-cliff").read_text()
    assert sudoers == "cliff ALL=(ALL) NOPASSWD:ALL\n"
    assert not any("chpasswd" in " ".join(c) or "--password" in c for c in cmds.calls)


def test_the_same_files_the_seed_names_are_written_with_their_modes_and_the_greeter_waits_for_the_home(tmp_path):
    result, cmds, root = run(tmp_path)
    login = (root / "etc/sddm.conf.d/baseline-autologin.conf").read_text()
    assert "User=cliff" in login
    assert (root / "etc/baseline-environment.json").read_text().startswith("{")
    assert ["systemctl", "daemon-reload"] in cmds.calls


def test_the_home_script_runs_every_boot_but_the_account_steps_only_once_per_instance(tmp_path):
    state = tmp_path / "state"
    first, cmds1, _ = run(tmp_path, state=state)
    assert any(c[:2] == ["/bin/sh", "-c"] and "baseline-home" in c[2] for c in cmds1.calls)
    second, cmds2, _ = run(tmp_path, cmds=Cmds(existing_users=("cliff",)), state=state)
    assert any(c[:2] == ["/bin/sh", "-c"] and "baseline-home" in c[2] for c in cmds2.calls)                    # the retained home is mounted again
    assert not any(c[0] == "useradd" for c in cmds2.calls)                                                      # the account is not made twice
    assert second["skipped"] == "already applied for this instance"


def test_an_existing_account_is_left_alone_even_for_a_new_instance(tmp_path):
    result, cmds, _ = run(tmp_path, cmds=Cmds(existing_users=("cliff",)))
    assert not any(c[0] == "useradd" for c in cmds.calls)


def test_a_failing_home_script_stops_before_any_account_is_made(tmp_path):
    class Failing(Cmds):
        def __call__(self, argv):
            if argv[:2] == ["/bin/sh", "-c"]:
                self.calls.append(list(argv))
                return 1, "", "Retained home disk is absent"
            return super().__call__(argv)
    cmds = Failing()
    with pytest.raises(sr.SeedError, match="home"):
        run(tmp_path, cmds=cmds)
    assert not any(c[0] == "useradd" for c in cmds.calls)                                                       # nothing signs in over a missing home


def test_a_name_or_path_that_is_not_plain_is_refused():
    bad = json.dumps({"users": [{"name": "root; rm -rf /", "uid": 1100}]})
    with pytest.raises(sr.SeedError):
        sr.apply("#cloud-config\n" + bad, "instance-id: x\n", run=Cmds(), root="/nonexistent", state_dir="/nonexistent")
    bad = json.dumps({"write_files": [{"path": "/etc/../../x", "content": "x"}]})
    with pytest.raises(sr.SeedError):
        sr.apply("#cloud-config\n" + bad, "instance-id: x\n", run=Cmds(), root="/nonexistent", state_dir="/nonexistent")


def test_every_step_and_any_failure_is_written_to_a_log_that_survives_the_boot(tmp_path):
    """Found on the rehearsal: Omarchy keeps no journal across boots, and a runner that fails silently cannot be diagnosed."""
    log = tmp_path / "state" / "baseline-seed.log"
    entries = []
    sr.record(entries.append, log, "made the account cliff")
    assert log.read_text().endswith("made the account cliff\n") and entries and "made the account cliff" in entries[0]
    sr.record(print, log, "second line")
    assert log.read_text().count("\n") == 2
    ok = sr.main_with(lambda: {"instance": "x"}, log_path=log)
    assert ok == 0 and '"instance": "x"' in log.read_text()
    def boom():
        raise sr.SeedError("a boot command failed (no space)")
    assert sr.main_with(boom, log_path=log) == 1 and "STOPPED: a boot command failed (no space)" in log.read_text()
    def odd():
        raise RuntimeError("unexpected")
    assert sr.main_with(odd, log_path=log) == 1 and "RuntimeError" in log.read_text()


def test_a_first_boot_command_that_fails_is_reported_in_the_result_not_swallowed(tmp_path):
    class Failing(Cmds):
        def __call__(self, argv):
            if argv[:1] == ["systemctl"] and "enable" in argv:
                self.calls.append(list(argv))
                return 1, "", "Unit qemu-guest-agent.service not found"
            return super().__call__(argv)
    result, cmds, _ = run(tmp_path, cmds=Failing())
    assert result["runcmd_failures"][0]["exit"] == 1 and "not found" in result["runcmd_failures"][0]["output"]
    assert result["users"] == ["cliff"]                                                                  # and the account was still made
