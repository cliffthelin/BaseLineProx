"""Building the Kasm base image (operator 2026-10-16: Kasm on top of Proxmox, ready immediately on a new setup, aligned with the overlay design; DR260).

The base is vanilla and reproducible: Debian 13, Docker, Kasm's installer and its container images preloaded. It holds NO Kasm install state and no secrets:
the installer runs at the target's first boot, so every setup generates its own passwords, keys and certificates. These are the pure parts."""
import subprocess

import pytest
import yaml

import kasm_build as kb

_NAMES = [("chrome", True), ("gimp", True), ("vs-code", True), ("ubuntu-noble-desktop", True), ("firefox", True), ("kali", False), ("terminal", True)]
GROUP = "68d557ac-4cac-42cc-a9f3-1c7c853de0f3"
SEED = yaml.safe_dump({"alembic_version": "abc", "images": [
    {"name": f"kasmweb/{n}:1.19.0-rolling-daily", "friendly_name": n.title(), "enabled": e, "hidden": False, "image_id": f"${{uuid:image_id:{i}}}", "cores": 2.0}
    for i, (n, e) in enumerate(_NAMES)],
    "group_images": [{"image_id": f"${{uuid:image_id:{i}}}", "group_id": GROUP} for i in range(len(_NAMES))]})
WS = kb.carried_images()
SVC = [kb.image_ref(s) for s in kb.SERVICE_IMAGES]


def test_images_are_referenced_by_the_static_version_tag_which_is_what_is_loaded():
    assert kb.image_ref("chrome") == "kasmweb/chrome:1.19.0" and kb.KASM_VERSION == "1.19.0"
    assert "kasmweb/proxy:1.19.0" in SVC and len(SVC) == 8


def test_two_workspace_entries_can_share_one_image_which_is_pulled_once():
    assert kb.carried_images() == [kb.image_ref(n) for n in ("chrome", "ubuntu-noble-desktop", "vs-code", "firefox", "terminal")]
    assert [w["image"] for w in kb.WORKSPACES].count("chrome") == 2


def test_the_choices_are_the_ones_the_operator_described():
    names = {w["friendly_name"]: w["persistent"] for w in kb.WORKSPACES}
    assert names["Browser (temporary)"] is False and names["Browser (personal)"] is True and names["Development desktop"] is True
    assert {"chrome", "vs-code"} <= {w["image"] for w in kb.WORKSPACES}           # two of the five default applications


def test_the_seeded_list_has_one_entry_per_choice_named_by_the_loaded_tag():
    out = yaml.safe_load(kb.trim_seed_yaml(SEED))
    assert [i["friendly_name"] for i in out["images"]] == [w["friendly_name"] for w in kb.WORKSPACES]
    assert {i["name"] for i in out["images"]} == set(kb.carried_images())                  # rolling-daily would be pulled; these are loaded
    assert all(i["enabled"] is True and i["hidden"] is False for i in out["images"])
    assert out["alembic_version"] == "abc"


def test_only_the_personal_choices_get_a_profile_path_and_it_is_per_user_then_per_workspace():
    out = yaml.safe_load(kb.trim_seed_yaml(SEED))
    by_name = {i["friendly_name"]: i for i in out["images"]}
    assert by_name["Browser (temporary)"]["persistent_profile_path"] is None and by_name["Terminal"]["persistent_profile_path"] is None
    for personal in ("Browser (personal)", "Development desktop", "VS Code", "Firefox"):
        assert by_name[personal]["persistent_profile_path"] == "/mnt/kasm_profiles/{user_id}/{image_id}"


def test_each_entry_has_its_own_image_id_so_two_entries_on_one_image_never_share_a_profile():
    ids = [i["image_id"] for i in yaml.safe_load(kb.trim_seed_yaml(SEED))["images"]]
    assert len(ids) == len(set(ids)) and all(i.startswith("${uuid:image_id:") for i in ids)


def test_every_kept_image_is_linked_to_the_users_group_and_nothing_else_is():
    """The seed has a group_images section (image -> the default All Users group). Kept as it was while most images are dropped, it names images that are not
    there; Postgres rejects it and the whole seed rolls back with no error, so no image appears (found 2026-10-16). It is rebuilt for exactly what is kept, and an
    image with no group link would not be visible to any user."""
    out = yaml.safe_load(kb.trim_seed_yaml(SEED))
    ids = [i["image_id"] for i in out["images"]]
    assert [row["image_id"] for row in out["group_images"]] == ids
    assert {row["group_id"] for row in out["group_images"]} == {GROUP}


def test_two_entries_on_one_image_are_both_linked_to_the_group_the_original_was_in():
    out = yaml.safe_load(kb.trim_seed_yaml(SEED))
    chromes = [i["image_id"] for i in out["images"] if i["name"] == "kasmweb/chrome:1.19.0"]
    assert len(chromes) == 2 and all(c in {r["image_id"] for r in out["group_images"]} for c in chromes)


def test_a_group_link_that_would_name_a_missing_image_is_an_error_not_a_silent_rollback():
    broken = yaml.safe_load(SEED)
    broken["group_images"] = [r for r in broken["group_images"] if r["image_id"] != "${uuid:image_id:0}"]          # chrome has no link in the release
    with pytest.raises(kb.KasmBuildError, match="chrome"):
        kb.trim_seed_yaml(yaml.safe_dump(broken))


def test_a_disabled_or_hidden_release_image_that_is_carried_is_shown():
    seed = yaml.safe_dump({"images": [{"name": "kasmweb/kali:1.19.0-rolling-daily", "enabled": False, "hidden": True, "image_id": "${uuid:image_id:1}"}],
                           "group_images": [{"image_id": "${uuid:image_id:1}", "group_id": GROUP}]})
    out = yaml.safe_load(kb.trim_seed_yaml(seed, [{"key": "k", "image": "kali", "friendly_name": "Kali", "persistent": True}]))
    assert out["images"][0]["enabled"] is True and out["images"][0]["hidden"] is False


def test_asking_for_an_image_the_release_does_not_list_is_an_error_not_a_silent_gap():
    with pytest.raises(kb.KasmBuildError, match="not-in-release"):
        kb.trim_seed_yaml(SEED, [{"key": "x", "image": "not-in-release", "friendly_name": "X", "persistent": False}])


def test_duplicate_workspace_names_or_keys_are_refused():
    twice = [kb.WORKSPACES[0], dict(kb.WORKSPACES[1], key=kb.WORKSPACES[0]["key"])]
    with pytest.raises(kb.KasmBuildError):
        kb.trim_seed_yaml(SEED, twice)


def test_the_profile_path_template_must_name_the_image_and_the_user():
    for bad in ("/mnt/kasm_profiles", "/mnt/kasm_profiles/{user_id}", "/mnt/kasm_profiles/{image_id}", "relative/{image_id}/{user_id}", "/mnt/../etc/{image_id}/{user_id}"):
        with pytest.raises(kb.KasmBuildError):
            kb.trim_seed_yaml(SEED, profile_path=bad)


def test_the_base_preparation_script_is_valid_shell_and_leaves_no_install_state_or_secrets():
    script = kb.prepare_script(SVC, WS)
    assert subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True).returncode == 0
    assert "kasm_release/install.sh" not in script                            # the installer is unpacked, never run, at build time
    for forbidden in ("--admin-password", "--user-password", "--db-password", "--manager-token"):
        assert forbidden not in script
    for generalise in ("cloud-init clean", "/etc/machine-id", "ssh_host_"):
        assert generalise in script                                          # the image is made generic: no machine id, host keys or cloud-init state
    assert script.rstrip().splitlines()[-1] == "poweroff"
    assert "systemctl enable baseline-kasm.service" in script
    assert "PREPARE-FAILED" in script and "trap" in script                  # a failure stops the build at once and says so


def test_every_carried_image_is_pulled_and_its_digest_reported():
    script = kb.prepare_script(SVC, WS)
    for ref in [*SVC, *WS]:
        assert f"pull {ref}" in script
    assert "IMAGE-DIGEST" in script and "RepoDigests" in script             # the builder records exactly what was loaded


def test_the_installer_gets_an_archive_that_lists_no_images_so_nothing_is_reloaded_at_first_boot():
    script = kb.prepare_script(SVC, WS)
    assert ": > /tmp/offline/service_images/images.txt" in script and "offline/service_images.tar.gz" in script


def test_the_cloud_config_installs_docker_and_runs_the_script_with_no_credentials():
    cfg = yaml.safe_load(kb.build_user_data(SVC, WS))
    assert {"docker.io", "docker-compose", "lsof", "qemu-guest-agent"} <= set(cfg["packages"])
    assert cfg.get("disable_root") is True and cfg.get("ssh_pwauth") is False
    assert "password" not in yaml.safe_dump({k: v for k, v in cfg.items() if k != "write_files"}).lower().replace("ssh_pwauth", "")
    assert any(f["path"] == "/root/prepare-kasm.sh" and f["permissions"] == "0700" for f in cfg["write_files"])


# --- the in-guest scripts: where Kasm's state lives, and how a fresh root gets Kasm back (DR260) -----------------------------------------------

def _sh(text):
    return subprocess.run(["bash", "-n"], input=text, text=True, capture_output=True)


def test_every_guest_script_is_valid_shell():
    for path, (mode, content) in kb.guest_files().items():
        if not path.endswith(".service"):
            assert _sh(content).returncode == 0, path


def test_the_guest_files_are_the_five_we_expect_with_safe_modes():
    files = kb.guest_files()
    assert set(files) == {"/usr/local/sbin/baseline-kasm-disks", "/usr/local/sbin/baseline-kasm-start", "/usr/local/sbin/baseline-kasm-up",
                          "/usr/local/sbin/baseline-kasm-install", "/etc/systemd/system/baseline-kasm.service"}
    assert files["/usr/local/sbin/baseline-kasm-install"][0] == "0700" and files["/etc/systemd/system/baseline-kasm.service"][0] == "0644"


def test_the_disk_script_never_formats_a_disk_that_has_anything_on_it():
    script = kb.guest_files()["/usr/local/sbin/baseline-kasm-disks"][1]
    assert "cmp -n 1048576" in script and "/dev/zero" in script and "blkid" in script     # blank means no filesystem is recognised and the first MiB is zeros
    assert script.index("blkid") < script.index("mkfs.ext4")
    assert "-E" not in script, "no lazy_itable_init override: the filesystem is made without writing out the whole disk"
    assert kb.ADMIN_DISK_SERIAL in script and kb.PROFILES_DISK_SERIAL in script          # disks are found by serial, never by device letter


def test_platform_state_is_on_the_admin_disk_and_user_profiles_on_the_personal_one():
    script = kb.guest_files()["/usr/local/sbin/baseline-kasm-disks"][1]
    assert "KASM_ADMIN /opt/kasm" in script and "KASM_PROFILES /mnt/kasm_profiles" in script
    assert kb.PROFILE_PATH.startswith("/mnt/kasm_profiles/")


def test_the_boot_driver_brings_up_the_disks_then_starts_kasm_only_when_it_was_installed():
    script = kb.guest_files()["/usr/local/sbin/baseline-kasm-up"][1]
    assert "/opt/kasm/.baseline/installed.json" in script and "baseline-kasm-start" in script
    assert script.index("baseline-kasm-disks") < script.index("baseline-kasm-start")                 # the disks first, then Kasm


def test_the_start_recreates_what_kasm_keeps_on_the_root_and_never_pulls():
    """A fresh root has no `kasm` user and no Docker network or volume records (found 2026-10-16: `id: kasm: no such user`, `network kasm_default_network not
    found`). Kasm's own bin/start also tries to pull images on every start; this starts the stack from the images in the base and touches no network."""
    script = kb.guest_files()["/usr/local/sbin/baseline-kasm-start"][1]
    assert "id -u kasm" in script and "docker network create --driver=bridge kasm_default_network" in script
    assert "type=none" in script and "o=bind" in script and "device=/opt/kasm/data/db" in script       # Postgres's data stays on the persistent admin disk
    assert "docker compose up -d" in script and "KASM_UID" in script and "KASM_GID" in script
    commands = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))          # the comments explain what is avoided
    for forbidden in ("docker pull", "bin/start", "upgrade_plugins", "bin/utils/pull"):
        assert forbidden not in commands, forbidden
    positions = [script.index(x) for x in ("id -u kasm", "docker network create", "docker volume create", "docker compose up -d")]
    assert positions == sorted(positions)


def test_the_base_carries_the_kasm_user_with_a_fixed_uid_so_ownership_on_the_persistent_disk_means_the_same_on_every_root():
    script = kb.prepare_script(SVC, WS)
    assert f"groupadd -g {kb.KASM_GID} kasm" in script and f"useradd -u {kb.KASM_UID} -g {kb.KASM_GID}" in script and "useradd -u 70" in script
    assert kb.KASM_UID == kb.KASM_GID and 1000 < kb.KASM_UID < 60000


def test_the_installer_takes_its_secrets_on_stdin_validated_and_never_writes_them_down():
    script = kb.guest_files()["/usr/local/sbin/baseline-kasm-install"][1]
    assert "read -r" in script and "A-Za-z0-9" in script                                    # allowlisted keys and a plain character set: nothing reaches a shell
    for flag in ("--install-profile noninteractive", "--accept-eula", "--offline-service", "--skip-egress", "--proxy-port", "db_init", "--use-static-images"):
        assert flag in script, flag
    assert "--offline-workspaces" not in script                                              # the workspaces are seeded by db_init from the trimmed list
    assert "set -x" not in script and "installed.json" in script
    for key in ("KASM_ADMIN_PASSWORD", "KASM_USER_PASSWORD", "KASM_DB_PASSWORD", "KASM_MANAGER_TOKEN"):
        assert key in script
    import re
    for printed in re.findall(r'echo\s+("[^"]*"|\'[^\']*\'|\S+)', script):                # a message may name the setting; nothing printed is a value
        assert "$value" not in printed and "secret[" not in printed, printed


def test_the_database_is_moved_onto_the_persistent_disk_after_it_is_initialised_and_before_anything_starts():
    """Kasm's `db_init -i` deletes and recreates its database volume with no options (found 2026-10-16), so a bind volume made beforehand is thrown away.
    The sequence that works: install without starting, seed, move the freshly initialised data onto the admin disk, re-create the volume as a bind onto it,
    then start, wait for health, and only then record the install."""
    script = kb.guest_files()["/usr/local/sbin/baseline-kasm-install"][1]
    order = ["--no-start", "db_init", "docker rm -f kasm_db", "docker volume rm", "docker volume create", "baseline-kasm-start", "__healthcheck",
             "installed.json"]          # a stopped container still holds the volume (found 2026-10-16), so it goes first; compose makes it again on start
    positions = [script.rindex(item) if item == "installed.json" else script.index(item) for item in order]      # the marker that counts is the one written last
    assert positions == sorted(positions), dict(zip(order, positions))
    assert "device=/opt/kasm/data/db" in script and "type=none" in script and "o=bind" in script
    assert 'cp -a "$SOURCE"/.' in script                     # the data is carried across, ownership and all
    assert "docker volume create" not in script.split("install.sh")[0]   # nothing is created before the installer, which would only replace it


def test_the_seed_tool_is_run_in_its_local_database_mode_like_the_installers_own_call():
    """`db_init -q <host>` means a remote database and skips starting the local one (found 2026-10-16: -q kasm_db seeded nothing); the installer passes `false`."""
    script = kb.guest_files()["/usr/local/sbin/baseline-kasm-install"][1]
    assert "db_init -s /opt/kasm-installer/seed/default_images_amd64.yaml -q false" in script


def test_the_install_is_recorded_only_when_kasm_answered_its_health_check():
    script = kb.guest_files()["/usr/local/sbin/baseline-kasm-install"][1]
    before_marker = script[:script.rindex("installed.json")]
    assert "__healthcheck" in before_marker and "exit 1" in before_marker.split("__healthcheck")[1]    # an unhealthy stack is a failure, never a marker


def test_the_database_move_refuses_to_overwrite_data_already_on_the_persistent_disk():
    script = kb.guest_files()["/usr/local/sbin/baseline-kasm-install"][1]
    assert "ls -A /opt/kasm/data/db" in script and "refusing" in script


def test_kasms_own_boot_unit_is_disabled_so_there_is_one_driver_and_it_never_pulls():
    script = kb.guest_files()["/usr/local/sbin/baseline-kasm-install"][1]
    assert "systemctl disable kasm.service" in script and "systemctl start kasm.service" not in script


def test_the_unit_runs_the_boot_driver_after_docker():
    unit = kb.guest_files()["/etc/systemd/system/baseline-kasm.service"][1]
    assert "After=docker.service" in unit and "ExecStart=/usr/local/sbin/baseline-kasm-up" in unit and "WantedBy=multi-user.target" in unit


def test_the_base_build_installs_those_files_and_enables_the_unit():
    cfg = yaml.safe_load(kb.build_user_data(SVC, WS))
    assert set(kb.guest_files()) <= {f["path"] for f in cfg["write_files"]}


def test_disk_serials_fit_the_virtio_limit_and_stay_distinct():
    """virtio-blk reports at most 20 characters of serial (found 2026-10-16: `baseline-kasm-profiles`, 22, arrived truncated and the disk was not found);
    Proxmox's `serial=` has the same limit."""
    for serial in (kb.ADMIN_DISK_SERIAL, kb.PROFILES_DISK_SERIAL):
        assert len(serial) <= 20 and serial.isascii() and serial.replace("-", "").isalnum(), serial
    assert kb.ADMIN_DISK_SERIAL != kb.PROFILES_DISK_SERIAL
    assert not kb.ADMIN_DISK_SERIAL.startswith(kb.PROFILES_DISK_SERIAL) and not kb.PROFILES_DISK_SERIAL.startswith(kb.ADMIN_DISK_SERIAL)


def test_the_registry_plugins_are_packed_in_the_base_and_handed_to_the_offline_installer():
    prepare = kb.prepare_script(["kasmweb/api:1.19.0"], [])
    assert "kasmweb/kasm-logging-plugin" in prepare and "kasmweb/kasm-network-plugin" in prepare
    assert "plugins.tar.gz" in prepare and "docker plugin rm" in prepare   # packed, then removed: the base keeps no install state
    install = kb.guest_files()["/usr/local/sbin/baseline-kasm-install"][1]
    assert "--offline-logger-plugin" in install and "--offline-network-plugin" in install


def test_the_lists_kasm_entry_chooses_the_workspaces_the_base_carries_else_the_default_set():
    chosen = [{"key": "browser", "image": "chrome", "friendly_name": "Browser", "persistent": True}]
    assert kb.workspaces_from_list([{"kind": "vm"}, {"kind": "kasm", "workspaces": chosen}]) == tuple(chosen)
    assert kb.workspaces_from_list([{"kind": "kasm", "workspaces": None}]) == kb.WORKSPACES and kb.workspaces_from_list([]) == kb.WORKSPACES
    assert kb.carried_images(kb.workspaces_from_list([{"kind": "kasm", "workspaces": chosen}])) == ["kasmweb/chrome:1.19.0"]    # a smaller list is a smaller base


def test_the_data_disks_are_up_before_the_installer_asks_whether_kasm_is_already_installed():
    """Found on a rebuilt VM (2026-10-17): the agent answers before the start-up service has mounted the disks; the marker is on them."""
    script = kb.guest_files()["/usr/local/sbin/baseline-kasm-install"][1]
    assert script.index("baseline-kasm-disks") < script.index("already installed")


def test_a_settings_seed_replaces_the_releases_own_before_the_installer_runs_and_only_when_there_is_one():
    script = kb.prepare_script(["kasmweb/api:1.19.0"], [])
    assert "default_properties.yaml" in script and "if [ -f /mnt/payload/default_properties.yaml ]" in script
    assert script.index("tar -xf") < script.index("default_properties.yaml")                  # after the release is unpacked, so it can overwrite the seed in it


def test_the_installer_accepts_a_registry_address_that_is_not_a_secret_and_nothing_else_unexpected():
    script = kb.guest_files()["/usr/local/sbin/baseline-kasm-install"][1]
    assert "KASM_REGISTRY_URL" in script and '--default-registry-url "$registry_url"' in script
    assert script.count('*) echo "unexpected setting"') == 1                                  # anything else is still refused
    assert "secret[KASM_REGISTRY_URL]" not in script and 'registry_url="$value"' in script


@pytest.mark.parametrize("url,ok", [("https://baseline.invalid:8100/kasm-registry/", True), ("http://10.0.0.5/", True), ("https://[fe80::1]:8100/r/", True),
                                    ("https://h.example/no-slash", False), ("ftp://h/", False), ("https://h/ x/", False), ("https://h/$(id)/", False), ("", False)])
def test_the_installers_registry_check_really_accepts_and_refuses_in_bash(url, ok):
    """Run in bash itself: a string match on the script missed that `\\]` does not escape a bracket in a POSIX regex (found 2026-10-17, when a good address was refused)."""
    script = kb.guest_files()["/usr/local/sbin/baseline-kasm-install"][1]
    line = next(l for l in script.splitlines() if l.strip().startswith('[[ "$value" =~ ^https?://'))
    check = line.strip().split(" || ")[0]
    result = subprocess.run(["bash", "-c", f'value="$1"; {check}', "x", url], capture_output=True)
    assert (result.returncode == 0) is ok, (url, result.returncode)
