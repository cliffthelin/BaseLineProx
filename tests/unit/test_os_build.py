"""Ready-made VM builds: the answer file, how it is put into an installer, and the in-guest application install. Nothing here boots anything."""
import gzip
import io
import subprocess

import pytest

import os_build as ob

APPS = {"chrome": {"file": "source.deb", "medium": "deb", "version": "155.0.8059.84-1", "sha256": "a" * 64, "url": "https://dl.google.com/x.deb"},
        "vscode": {"file": "source.tar.gz", "medium": "tar.gz", "version": "1.142.0", "sha256": "b" * 64, "url": "https://x"}}


def test_an_answer_file_added_to_an_initrd_is_readable_by_cpio_after_the_original_content():
    original = gzip.compress(b"original-archive-bytes")
    combined = ob.initrd_with(original, {"preseed.cfg": b"d-i x string y\n", "other": b"abc"})
    assert combined.startswith(original)                                      # the original is untouched, ours is appended: the kernel unpacks both
    appended = gzip.decompress(combined[len(original):])
    listing = subprocess.run(["cpio", "-it"], input=appended, capture_output=True)
    assert listing.stdout.decode().split() == ["preseed.cfg", "other"]
    extracted = subprocess.run(["cpio", "-i", "--to-stdout", "preseed.cfg"], input=appended, capture_output=True)
    assert extracted.stdout == b"d-i x string y\n"


def test_a_file_name_that_could_escape_the_archive_root_is_refused():
    for name in ("../etc/passwd", "a/b", "/abs", "", "x" * 200):
        with pytest.raises(ob.BuildError):
            ob.initrd_with(b"", {name: b"x"})


def test_the_debian_answers_leave_no_question_no_password_and_a_disk_that_boots_anywhere():
    answers = ob.debian_preseed()
    assert "d-i passwd/user-password-crypted password !" in answers and "d-i passwd/root-login boolean false" in answers      # no usable credential in the base
    assert "force-efi-extra-removable boolean true" in answers and "exit/poweroff boolean true" in answers
    assert "keyboard-configuration/layoutcode string us" in answers and "keyboard-configuration keyboard-configuration/layout select English (US)" in answers   # the question that stopped the first run
    assert "cloud-init qemu-guest-agent" in answers and "tasksel tasksel/first multiselect standard, gnome-desktop" in answers
    assert all(line.split(" ")[0] in ("d-i", "tasksel", "popularity-contest", "keyboard-configuration") for line in answers.strip().splitlines())


def test_a_late_command_is_one_line_and_other_values_must_be_plain():
    assert "preseed/late_command string echo hi" in ob.debian_preseed(late_command="echo hi")
    for bad in ({"late_command": "a\nb"}, {"disk": "vda; rm"}, {"hostname": "Bad Host"}, {"mirror": "x y"}, {"tasks": "a; b"}, {"packages": ("ok", "bad pkg")}):
        with pytest.raises(ob.BuildError):
            ob.debian_preseed(**bad)


def test_the_guest_script_checks_every_package_against_its_recorded_hash_before_installing_it():
    script = ob.debian_apps_script(APPS)
    assert script.index("sha256sum -c") < script.index("apt-get install -y ./chrome/source.deb")
    assert f"echo '{'a' * 64}  chrome/source.deb' | sha256sum -c -" in script and "set -eu" in script
    assert "tar -xzf vscode/source.tar.gz -C /opt/vscode" in script and "/usr/local/bin/code" in script
    assert "chrome=155.0.8059.84-1" in script and ob.PREBUILT_RECORD in script
    assert subprocess.run(["sh", "-n"], input=script, text=True, capture_output=True).returncode == 0


def test_an_application_without_a_recorded_hash_or_with_an_odd_name_is_refused():
    for change in ({"sha256": ""}, {"sha256": "xyz"}, {"file": "a b.deb"}, {"file": "../x.deb"}, {"medium": "rpm"}, {"version": "1; rm -rf /"}):
        with pytest.raises(ob.BuildError):
            ob.debian_apps_script({"chrome": {**APPS["chrome"], **change}})
    with pytest.raises(ob.BuildError):
        ob.debian_apps_script({"Bad App": APPS["chrome"]})


def test_every_listed_system_says_how_it_is_built():
    assert set(ob.METHODS) == {"debian", "ubuntu", "omarchy", "nixos", "bazzite", "cachyos", "fydeos", "qubes"}
    assert all(m["method"] and m["network"] for m in ob.METHODS.values())


def test_the_ubuntu_build_config_installs_the_desktop_runs_the_script_from_the_payload_and_creates_no_account():
    config = ob.ubuntu_cloud_config()
    assert config.startswith("#cloud-config") and "  - ubuntu-desktop-minimal" in config and "  - qemu-guest-agent" in config
    assert ob.APPS_LABEL in config and "install-apps.sh" in config and "mode: poweroff" in config
    for forbidden in ("users:", "passwd", "ssh_authorized_keys", "chpasswd"):
        assert forbidden not in config
    with pytest.raises(ob.BuildError):
        ob.ubuntu_cloud_config(packages=("ok", "not ok; rm"))


def test_the_nixos_configuration_boots_anywhere_creates_no_user_and_names_what_it_installs():
    config = ob.nix_configuration()
    assert 'efiInstallAsRemovable = true' in config and 'canTouchEfiVariables = false' in config           # no firmware variable is needed
    assert '/dev/disk/by-label/nixos' in config and '/dev/disk/by-label/ESP' in config and "virtio_scsi" in config and "nvme" in config
    assert "users.users" not in config and "initialPassword" not in config and "hashedPassword" not in config
    assert "vscode google-chrome spotify" in config and "services.cloud-init.enable = true" in config
    with pytest.raises(ob.BuildError):
        ob.nix_configuration(packages=("ok", "bad pkg"))


def test_the_apps_nixos_has_no_package_for_are_named_so_they_are_reported_not_skipped():
    assert set(ob.NIX_MISSING_APPS) == {"chatgpt", "claude"}


def test_the_omarchy_drive_defers_the_account_names_no_secret_and_lays_out_a_whole_disk():
    import json
    files = ob.omarchy_cidata(disk_bytes=64 * 1024 ** 3)
    assert set(files) == {"user_configuration.json", "defer-provisioning", "user_encrypt_installation.txt"} and files["defer-provisioning"] == "" and files["user_encrypt_installation.txt"] == "false\n"
    config = json.loads(files["user_configuration.json"])
    assert config["omarchy_install"]["defer_provisioning"] is True and config["omarchy_install"]["mode"] == "full_disk" and config["version"] == "3.0.9"
    assert "disk_encryption" not in config["disk_config"]
    boot, main = config["disk_config"]["device_modifications"][0]["partitions"]
    assert boot["mountpoint"] == "/boot" and boot["flags"] == ["boot", "esp"] and main["fs_type"] == "btrfs"
    assert boot["start"]["value"] + boot["size"]["value"] == main["start"]["value"]                                     # no gap, no overlap
    assert main["start"]["value"] + main["size"]["value"] <= 64 * 1024 ** 3 - 1024 ** 2                                 # leaves room for the backup partition table
    assert "qemu-guest-agent" in config["packages"] and config["services"] == ["qemu-guest-agent"]
    assert "password" not in files["user_configuration.json"].lower()


def test_an_encrypted_omarchy_layout_names_the_root_partition_and_a_small_disk_or_odd_value_is_refused():
    import json
    config = json.loads(ob.omarchy_cidata(disk_bytes=64 * 1024 ** 3, encrypt=True)["user_configuration.json"])
    assert config["disk_config"]["disk_encryption"]["partitions"] == ["8c2c2b92-1070-455d-b76a-56263bab24aa"]
    for bad in ({"disk_bytes": 8 * 1024 ** 3}, {"disk_bytes": 64 * 1024 ** 3, "hostname": "Bad Host"}, {"disk_bytes": 64 * 1024 ** 3, "packages": ("ok", "x; y")}, {"disk_bytes": 64 * 1024 ** 3, "kernel": "evil"}):
        with pytest.raises(ob.BuildError):
            ob.omarchy_user_configuration(**bad)


def test_the_bazzite_kickstart_installs_the_image_on_the_iso_wipes_the_disk_and_makes_no_account():
    ks = ob.bazzite_kickstart()
    assert "ostreecontainer --url=/run/install/repo/bazzite-stable --transport=oci" in ks
    assert "clearpart --all" in ks and "rootpw --lock" in ks and ks.rstrip().endswith("poweroff")
    for forbidden in ("\nuser ", "--plaintext", "password"):
        assert forbidden not in ks
    for bad in ({"hostname": "Bad Host"}, {"image": "/etc/passwd"}, {"image": "/run/install/repo/../x"}):
        with pytest.raises(ob.BuildError):
            ob.bazzite_kickstart(**bad)


def test_the_cachyos_config_uses_throwaway_long_passwords_and_the_documented_headless_keys():
    import json
    config = json.loads(ob.cachyos_config(user_pass="u" * 24, root_pass="r" * 24))
    assert config["headless_mode"] is True and config["allow_auto_partition"] is True and config["device"] == "/dev/vda"
    assert config["user_name"] == ob.CACHY_BUILD_USER and config["post_install"] == "/root/post-install.sh"
    for short in ({"user_pass": "short", "root_pass": "r" * 24}, {"user_pass": "u" * 24, "root_pass": "x"}):
        with pytest.raises(ob.BuildError):
            ob.cachyos_config(**short)
    with pytest.raises(ob.BuildError):
        ob.cachyos_config(user_pass="u" * 24, root_pass="r" * 24, disk="/dev/vda; rm")


def test_the_cachyos_post_install_adds_the_agent_and_cloud_init_and_a_removable_boot_loader():
    import subprocess
    script = ob.cachyos_post_install()
    assert "cloud-init qemu-guest-agent" in script and "--removable" in script and "arch-chroot /mnt" in script
    assert script.index("mount -o subvol=@") < script.index("arch-chroot /mnt") and "umount -R /mnt" in script           # the installer leaves the target unmounted, so this mounts it itself
    assert subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True).returncode == 0


def test_the_first_boot_seed_makes_the_owners_account_with_no_password_at_all():
    seed = ob.first_boot_seed(username="alex", hostname="desk", instance_id="vm-101")
    assert seed["user-data"].startswith("#cloud-config") and "lock_passwd: true" in seed["user-data"] and "passwd:" not in seed["user-data"].replace("lock_passwd:", "")
    assert "uid: 1100" in seed["user-data"] and "sudo: ALL=(ALL) NOPASSWD:ALL" in seed["user-data"] and "ssh_pwauth: false" in seed["user-data"] and "disable_root: true" in seed["user-data"]
    assert seed["meta-data"] == "instance-id: vm-101\nlocal-hostname: desk\n"


def test_an_ssh_key_is_optional_and_odd_values_are_refused():
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl alex@host"
    assert key in ob.first_boot_seed(username="alex", ssh_keys=[key], hostname="desk", instance_id="i")["user-data"]
    for bad in ({"username": "Bad User"}, {"hostname": "Bad Host"}, {"ssh_keys": ["not a key; rm -rf /"]}):
        with pytest.raises(ob.BuildError):
            ob.first_boot_seed(**{"username": "alex", "hostname": "desk", "instance_id": "i", **bad})


def test_the_bazzite_kickstart_installs_the_seed_runner_and_a_unit_that_runs_before_the_login_screen_and_creates_no_account():
    ks = ob.bazzite_kickstart(runner="print('runner body')\n")
    assert "%post --erroronfail" in ks and ks.rstrip().endswith("%end")
    assert "print('runner body')" in ks and "/etc/baseline-seed/seed_runner.py" in ks
    assert "Before=" in ks and "sddm.service" in ks and "display-manager.service" in ks
    assert "multi-user.target.wants/baseline-seed.service" in ks                                # enabled without a running systemd
    assert "rootpw --lock" in ks and "user --name" not in ks and "--password" not in ks         # still no account in the base
    assert ks.count("BASELINE_SEED_EOF") % 2 == 0
    with pytest.raises(ob.BuildError):
        ob.bazzite_kickstart(runner="x\nBASELINE_SEED_EOF\nrm -rf /\n")                         # the runner text cannot end its own heredoc


def test_the_bazzite_kickstart_without_a_runner_is_the_old_one():
    assert "%post" not in ob.bazzite_kickstart()
