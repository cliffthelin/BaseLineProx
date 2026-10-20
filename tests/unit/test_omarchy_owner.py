"""Omarchy's own first-boot script, fed from the seed: no form, no typed password."""
import pytest

import omarchy_owner as oo

VENDOR = '''#!/bin/bash
set -euo pipefail
STATE_FILE=/run/omarchy-provision-owner.state
LOG_FILE=/var/log/omarchy-provision-owner.log
create_user() { echo making "$username"; }
run_provisioning() {
  create_user
}
run_setup() { echo interactive; }
main() { run_setup; }

main
'''


class Cmds:
    def __init__(self, code=0, existing=False):
        self.calls, self.code, self.existing = [], code, existing

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[:2] == ["getent", "passwd"]:
            return (0 if self.existing else 2), "", ""
        if argv[0] == "bash":
            return self.code, "", "boom" if self.code else ""
        return 0, "", ""


def test_the_vendor_script_is_patched_to_run_its_own_provisioning_with_the_seeds_answers_and_no_form():
    patched = oo.seeded_script(VENDOR, owner="cliff", hostname="work")
    assert patched.count("\nmain\n") == 0 and patched.rstrip().endswith("run_provisioning >>\"$LOG_FILE\" 2>&1")
    assert "username=cliff" in patched and "hostname=work" in patched and "timezone=UTC" in patched
    assert "secrets.token_urlsafe" in patched                                                                  # a random password nobody sees; it is locked straight afterwards
    assert "run_setup" in patched and "keyboard_form" not in patched.split("run_setup() {")[1].split("}")[0]   # the vendor's own functions are untouched


def test_a_script_that_is_not_the_one_this_was_written_for_is_refused_not_guessed():
    for bad in (VENDOR.replace("run_provisioning()", "other()"), VENDOR.replace("\nmain\n", "\nmain\nmain\n"), VENDOR.replace("\nmain\n", "\n"), "echo hi\n"):
        with pytest.raises(oo.OwnerError):
            oo.seeded_script(bad, owner="cliff", hostname="work")


def test_names_that_are_not_plain_are_refused():
    for owner, host in (("root; rm -rf /", "work"), ("Cliff", "work"), ("cliff", "work; x"), ("", "work")):
        with pytest.raises(oo.OwnerError):
            oo.seeded_script(VENDOR, owner=owner, hostname=host)


def test_after_provisioning_the_passwords_are_locked_autologin_stays_and_sudo_needs_no_prompt(tmp_path):
    cmds = Cmds()
    root = tmp_path / "root"
    (root / "etc/systemd/system/graphical.target.wants").mkdir(parents=True)
    (root / "etc/systemd/system/omarchy-provision-autologin-once.service").write_text("x")
    (root / "etc/systemd/system/graphical.target.wants/omarchy-provision-autologin-once.service").symlink_to("../omarchy-provision-autologin-once.service")
    (root / "var/lib/omarchy/provisioning").mkdir(parents=True)
    (root / "var/lib/omarchy/provisioning/pending").write_text("")
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/bin/omarchy-provision-owner").write_text(VENDOR)
    oo.provision("cliff", "work", run=cmds, root=root, work_dir=tmp_path / "work")
    assert ["passwd", "-l", "cliff"] in cmds.calls and ["passwd", "-l", "root"] in cmds.calls
    assert (root / "etc/sddm.conf.d/baseline-autologin.conf").read_text() == "[Autologin]\nUser=cliff\nSession=omarchy.desktop\n"
    assert (root / "etc/sudoers.d/90-baseline-cliff").read_text() == "cliff ALL=(ALL) NOPASSWD:ALL\n"
    assert not (root / "etc/systemd/system/omarchy-provision-autologin-once.service").exists()                 # the one-boot autologin cleanup would take the sign-in away
    assert any(c[0] == "bash" for c in cmds.calls) and ["systemctl", "daemon-reload"] in cmds.calls


def test_nothing_happens_when_the_system_is_already_provisioned(tmp_path):
    cmds = Cmds()
    root = tmp_path / "root"
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/bin/omarchy-provision-owner").write_text(VENDOR)
    assert oo.provision("cliff", "work", run=cmds, root=root, work_dir=tmp_path / "w")["skipped"] == "no first-boot setup is pending"
    assert cmds.calls == []


def test_a_failed_provisioning_run_is_reported_and_nothing_is_locked_or_signed_in(tmp_path):
    root = tmp_path / "root"
    (root / "var/lib/omarchy/provisioning").mkdir(parents=True)
    (root / "var/lib/omarchy/provisioning/pending").write_text("")
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/bin/omarchy-provision-owner").write_text(VENDOR)
    cmds = Cmds(code=1)
    with pytest.raises(oo.OwnerError, match="boom"):
        oo.provision("cliff", "work", run=cmds, root=root, work_dir=tmp_path / "w")
    assert not any(c[0] == "passwd" for c in cmds.calls) and not (root / "etc/sddm.conf.d/baseline-autologin.conf").exists()


def test_the_account_is_made_first_with_the_fixed_uid_so_omarchys_script_resumes_it_instead_of_picking_a_uid(tmp_path):
    root = tmp_path / "root"
    (root / "var/lib/omarchy/provisioning").mkdir(parents=True)
    (root / "var/lib/omarchy/provisioning/pending").write_text("")
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/bin/omarchy-provision-owner").write_text(VENDOR)
    cmds = Cmds()
    oo.provision("cliff", "work", run=cmds, root=root, work_dir=tmp_path / "w")
    useradd = next(c for c in cmds.calls if c[0] == "useradd")
    assert useradd[useradd.index("-u") + 1] == "1100" and useradd[-1] == "cliff"
    assert cmds.calls.index(useradd) < next(i for i, c in enumerate(cmds.calls) if c[0] == "bash")             # before Omarchy's own script runs
    again = Cmds(existing=True)
    oo.provision("cliff", "work", run=again, root=root, work_dir=tmp_path / "w2")
    assert not any(c[0] == "useradd" for c in again.calls)                                                      # an account that is already there is left as it is
