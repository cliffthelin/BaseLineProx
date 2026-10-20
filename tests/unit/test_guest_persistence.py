"""Monitored files and folders of a guest (accounts' sign-ins, Bluetooth pairings, saved networks, keys, AI settings) live on the retained disk, so a change made on the running machine
is a change to the persistent layer, never to the disposable OS layer. Checked against real shell runs in a temp tree."""
import os
import subprocess

import guest_persistence as gp


def test_defaults_cover_bluetooth_networks_keys_and_ai():
    paths = set(gp.MONITORED)
    assert {"/var/lib/bluetooth", "/etc/NetworkManager/system-connections", "/etc/ssh"} <= paths
    assert any("ollama" in p or "claude" in p for p in paths)


def test_only_plain_absolute_folders_are_accepted():
    for bad in ("etc/x", "/", "/etc", "/etc/../root", "/etc/a b;rm", "/run/baseline-vault", "/home", "/home/x"):
        try:
            gp.check_path(bad)
        except gp.PersistenceError:
            continue
        raise AssertionError(bad)


def test_the_unit_waits_for_the_home_and_runs_before_the_services_that_use_the_folders():
    files = {f["path"]: f for f in gp.guest_files()}
    unit = files["/etc/systemd/system/baseline-persist-monitored.service"]["content"]
    assert "ConditionPathExists=/run/baseline-home-ready" in unit and "Before=" in unit and "bluetooth.service" in unit
    assert files["/usr/local/sbin/baseline-persist-monitored"]["permissions"] == "0755"


def _run(script, tmp_path, paths):
    store = tmp_path / "home" / ".baseline-overlay"
    ready = tmp_path / "ready"
    ready.write_text("")
    text = script.replace("/run/baseline-home-ready", str(ready)).replace("/home/.baseline-overlay", str(store))
    for p in paths:
        text = text.replace(p, str(tmp_path / p.lstrip("/")))
    text = text.replace("mount --bind", "ln -sfn").replace("mountpoint -q", "test -L")           # a symlink stands in for the bind mount in an unprivileged test
    return subprocess.run(["sh", "-c", text], capture_output=True, text=True), store


def test_existing_content_moves_to_the_retained_disk_once_and_later_changes_stay_there(tmp_path):
    target = tmp_path / "var/lib/bluetooth"
    (target / "AA:BB").mkdir(parents=True)
    (target / "AA:BB" / "info").write_text("paired")
    script = gp.script(["/var/lib/bluetooth"])
    done, store = _run(script, tmp_path, ["/var/lib/bluetooth"])
    assert done.returncode == 0, done.stderr
    kept = store / "var-lib-bluetooth"
    assert (kept / "AA:BB" / "info").read_text() == "paired"
    (kept / "NEW").write_text("added later")                    # a change on the running machine lands in the persistent folder
    again, _ = _run(script, tmp_path, ["/var/lib/bluetooth"])
    assert again.returncode == 0 and (kept / "AA:BB" / "info").read_text() == "paired" and (kept / "NEW").exists()


def test_a_second_run_never_reseeds_over_what_the_retained_disk_holds(tmp_path):
    kept = tmp_path / "home" / ".baseline-overlay" / "etc-ssh"
    kept.mkdir(parents=True)
    (kept / "ssh_host_key").write_text("persisted key")
    (kept / ".seeded").write_text("")
    (tmp_path / "etc/ssh").mkdir(parents=True)
    (tmp_path / "etc/ssh" / "ssh_host_key").write_text("image key")
    done, _ = _run(gp.script(["/etc/ssh"]), tmp_path, ["/etc/ssh"])
    assert done.returncode == 0 and (kept / "ssh_host_key").read_text() == "persisted key"


def test_nothing_runs_when_the_home_is_not_there(tmp_path):
    script = gp.script(["/etc/ssh"])
    assert "baseline-home-ready" in script


def test_every_prebuilt_seed_keeps_the_monitored_folders_on_the_retained_disk():
    import json
    import prebuilt_environment as pe
    config = json.loads(pe.cloud_config("ubuntu", owner="cliff", initialize_home=True, hostname="u1").split("\n", 1)[1])
    assert "/usr/local/sbin/baseline-persist-monitored" in {f["path"] for f in config["write_files"]}
    assert ["systemctl", "enable", "--now", "baseline-persist-monitored.service"] in config["runcmd"]


def test_folder_names_follow_the_hosts_own_scheme():
    import persist_bind_mounts as pbm
    assert gp.subdir_for("/etc/baseline") == pbm.REDIRECT_PATHS["/etc/baseline"] == "etc-baseline"
    assert gp.subdir_for("/etc/ssh") == "etc-ssh"
