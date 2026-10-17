"""Self-contained installer: the first-boot hook carried inside the ISO, and storage applied by the installed
system itself. Real tools only (sh, tar, base64, the real assistant's validate-answer); no fakes or mocks."""
import os
import subprocess
from pathlib import Path

import pytest

import first_boot_hook as fbh
import self_installer as si
import single_drive_storage as storage

REPO = Path(__file__).resolve().parents[2]
ASSISTANT = Path("/var/tmp/baseline-self-installer/acquire/extracted/usr/bin/proxmox-auto-install-assistant")
SERIAL = "MD89N41071210AP4E"


def _root_ancestry(*disks):
    return {"blockdevices": [{"name": "/dev/mapper/pve-root", "type": "lvm", "children": [
        {"name": "/dev/sda3", "type": "part", "children": [dict(d, type="disk") for d in disks]}]}]}


def test_the_running_root_disk_is_identified_by_its_own_ancestry():
    assert storage.serial_of_root_disk(_root_ancestry({"name": "/dev/sda", "serial": SERIAL})) == SERIAL


@pytest.mark.parametrize("listing", [
    {"blockdevices": []},
    _root_ancestry({"name": "/dev/sda", "serial": ""}),
    _root_ancestry({"name": "/dev/sda", "serial": SERIAL}, {"name": "/dev/sdb", "serial": "OTHER"}),
    _root_ancestry({"name": "/dev/sda", "serial": "bad serial!"}),
])
def test_an_ambiguous_or_unidentified_root_disk_is_refused(listing):
    with pytest.raises(storage.StorageError):
        storage.serial_of_root_disk(listing)


def test_first_boot_storage_only_ever_binds_to_the_running_root():
    with pytest.raises(storage.StorageError):
        storage.RunningRunner(None, {"root_mount": "/target"})


def test_the_hook_fits_proxmoxs_first_boot_size_limit():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        hook = fbh.build_hook(REPO, Path(tmp) / "baseline-first-boot")
        assert os.access(hook, os.X_OK)
        assert hook.stat().st_size < fbh.PROXMOX_HOOK_LIMIT == 1024 * 1024


def test_the_hook_takes_the_whole_installer_from_the_attached_medium_with_real_tools(tmp_path):
    import shutil
    media = tmp_path / "media"
    for name in ("baseline", "boot", "automation", "tests"):
        shutil.copytree(REPO / name, media / "baseline-src" / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".test-work*"))
    hook = fbh.build_hook(REPO, tmp_path / "baseline-first-boot")
    dest = tmp_path / "opt-baseline-src"
    proc = subprocess.run(["sh", str(hook)], capture_output=True, text=True,
                          env=dict(os.environ, BASELINE_HOOK_DEST=str(dest), BASELINE_HOOK_MEDIA=str(media),
                                   BASELINE_HOOK_EXTRACT_ONLY="1"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for rel in ("boot/provision.sh", "baseline/bin/baseline-first-boot-install",
                "baseline/bin/baseline-single-drive-storage", "baseline/lib/single_drive_storage.py",
                "automation", "tests/console_font_check.sh"):
        assert (dest / rel).exists(), rel


def test_the_hook_stops_when_no_installer_medium_carries_the_source(tmp_path):
    hook = fbh.build_hook(REPO, tmp_path / "baseline-first-boot")
    (tmp_path / "empty-media").mkdir()
    proc = subprocess.run(["sh", str(hook)], capture_output=True, text=True,
                          env=dict(os.environ, BASELINE_HOOK_DEST=str(tmp_path / "dest"),
                                   BASELINE_HOOK_MEDIA=str(tmp_path / "empty-media"), BASELINE_HOOK_EXTRACT_ONLY="1"))
    assert proc.returncode != 0 and not (tmp_path / "dest").exists()


def test_a_hook_without_the_on_target_installer_is_never_built(tmp_path):
    (tmp_path / "repo/boot").mkdir(parents=True)
    with pytest.raises(fbh.HookError):
        fbh.build_hook(tmp_path / "repo", tmp_path / "hook")


def _installer():
    import importlib.machinery
    import importlib.util
    path = REPO / "baseline/bin/baseline-first-boot-install"
    loader = importlib.machinery.SourceFileLoader("first_boot_install", str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("first_boot_install", loader))
    loader.exec_module(module)
    return module


def test_the_exact_iso_length_is_read_from_a_real_iso_header(tmp_path):
    import shutil
    if not shutil.which("xorriso"):
        pytest.skip("xorriso is not installed")
    (tmp_path / "content").mkdir()
    (tmp_path / "content/file").write_bytes(b"x" * 300_000)
    iso = tmp_path / "small.iso"
    subprocess.run(["xorriso", "-as", "mkisofs", "-quiet", "-V", "TEST", "-o", str(iso), str(tmp_path / "content")],
                   check=True, capture_output=True)
    with open(iso, "rb") as stream:
        assert _installer().iso_length(stream) == iso.stat().st_size
    with pytest.raises(RuntimeError):
        _installer().iso_length(__import__("io").BytesIO(b"\0" * 40000))


def test_the_package_list_is_read_from_provision_sh_itself():
    import offline_cache
    packages = offline_cache.provision_packages((REPO / "boot/provision.sh").read_text())
    for name in ("cage", "chromium", "podman", "tmux", "nodejs", "kbd"):
        assert name in packages
    assert all(p and not p.startswith("-") for p in packages)


def test_the_cache_also_carries_what_first_boot_authorization_installs():
    import firstboot_statemachine
    import offline_cache
    packages = offline_cache.required_packages(REPO)
    for name in firstboot_statemachine.DIAGNOSTIC_PACKAGES:
        assert name in packages
    assert "chromium" in packages and len(packages) == len(set(packages))


def test_carried_files_are_verified_against_the_manifest(tmp_path):
    import offline_cache as installer
    (tmp_path / "pool").mkdir()
    (tmp_path / "pool/a.deb").write_bytes(b"package-a")
    manifest = installer.build_manifest(tmp_path)
    assert installer.verify_manifest(tmp_path, manifest) == 1
    (tmp_path / "pool/a.deb").write_bytes(b"tampered")
    with pytest.raises(RuntimeError):
        installer.verify_manifest(tmp_path, manifest)
    (tmp_path / "pool/a.deb").write_bytes(b"package-a")
    (tmp_path / "pool/extra.deb").write_bytes(b"not listed")
    with pytest.raises(RuntimeError):
        installer.verify_manifest(tmp_path, manifest)


def test_the_offline_cache_is_mapped_onto_the_iso_next_to_the_source():
    import iso_builder
    argv = iso_builder.remaster_argv(Path("/in.iso"), Path("/out.iso"), Path("/stage"), cache_dir=Path("/cache"))
    assert argv[argv.index("/stage") - 1] == "-map" and argv[argv.index("/stage") + 1] == "/baseline-src"
    assert argv[argv.index("/cache") - 1] == "-map" and argv[argv.index("/cache") + 1] == "/baseline-cache"
    assert "/baseline-cache" not in iso_builder.remaster_argv(Path("/in.iso"), Path("/out.iso"), Path("/stage"))


def test_the_real_remaster_carries_the_cache_inside_a_real_iso(tmp_path):
    import shutil
    import iso_builder
    if not shutil.which("xorriso"):
        pytest.skip("xorriso is not installed")
    (tmp_path / "src").mkdir(); (tmp_path / "src/f").write_text("x")
    source = tmp_path / "source.iso"
    subprocess.run(["xorriso", "-as", "mkisofs", "-quiet", "-o", str(source), str(tmp_path / "src")], check=True,
                   capture_output=True)
    (tmp_path / "stage/boot").mkdir(parents=True); (tmp_path / "stage/boot/provision.sh").write_text("#!/bin/sh\n")
    (tmp_path / "cache/apt").mkdir(parents=True); (tmp_path / "cache/MANIFEST.json").write_text("{}\n")
    out = tmp_path / "out.iso"
    subprocess.run(iso_builder.remaster_argv(source, out, tmp_path / "stage", cache_dir=tmp_path / "cache"),
                   check=True, capture_output=True)
    found = subprocess.run(iso_builder.find_in_iso_argv(out, "/baseline-cache/MANIFEST.json"), capture_output=True,
                           text=True)
    assert "MANIFEST.json" in found.stdout


def test_prepare_iso_embeds_the_hook_only_for_a_self_contained_installer():
    base = si.prepare_iso_args("https://10.0.2.100:8443/answer/x", "AA:BB", None)
    assert base == ["--url", "https://10.0.2.100:8443/answer/x", "--cert-fingerprint", "AA:BB"]
    hooked = si.prepare_iso_args("https://10.0.2.100:8443/answer/x", "AA:BB", Path("/w/baseline-first-boot"))
    assert hooked[-2:] == ["--on-first-boot", "/w/baseline-first-boot"]


def _answer(first_boot):
    return si.render_answer(fqdn="baseline.local", password_hash="$6$abcdefgh$" + "x" * 86, disk_serial=SERIAL,
                          lvm_maxroot=32, lvm_maxvz=64, lvm_swapsize=4, first_boot=first_boot)


def test_the_answer_file_runs_the_hook_from_the_iso_once_networking_is_up():
    text = _answer(True)
    assert "[first-boot]" in text and 'source = "from-iso"' in text and 'ordering = "network-online"' in text
    assert "[first-boot]" not in _answer(False)


@pytest.mark.skipif(not ASSISTANT.exists(), reason="the verified proxmox-auto-install-assistant is not on this machine")
def test_the_real_assistant_accepts_the_answer_file_with_the_hook(tmp_path):
    answer = tmp_path / "answer.toml"
    answer.write_text(_answer(True))
    proc = subprocess.run([str(ASSISTANT), "validate-answer", str(answer)], capture_output=True, text=True)
    assert proc.returncode == 0 and "successfully" in proc.stdout + proc.stderr, proc.stdout + proc.stderr


# -- Reboot after install (fix for the 2026-10-10 rehearsal's reboot loop) ---------------------------------------

@pytest.mark.parametrize("cgroup,unit", [
    ("0::/system.slice/proxmox-first-boot-network-online.service\n", "proxmox-first-boot-network-online.service"),
    ("12:pids:/system.slice/proxmox-first-boot-multi-user.service\n1:name=systemd:/system.slice/"
     "proxmox-first-boot-multi-user.service\n", "proxmox-first-boot-multi-user.service"),
    ("0::/user.slice/user-0.slice/session-3.scope\n", None),            # run by hand, not by a service
    ("", None),
])
def test_the_invoking_service_is_read_from_the_cgroup(cgroup, unit):
    assert _installer().invoking_unit(cgroup) == unit


def test_the_reboot_is_queued_after_the_invoking_unit_never_run_inline():
    argv = _installer().reboot_after_argv("proxmox-first-boot-network-online.service")
    assert argv[0] == "systemd-run" and "--no-block" in argv
    assert "--property=After=proxmox-first-boot-network-online.service" in argv
    assert argv[-2:] == ["systemctl", "reboot"]


def test_an_already_complete_install_never_reboots_again(tmp_path, monkeypatch):
    """Returning successfully is what lets Proxmox's ExecStartPost remove its pending flag, so a re-run after
    completion must do nothing at all - this is what ends any leftover loop."""
    module = _installer()
    monkeypatch.setattr(module, "STATE", tmp_path)
    monkeypatch.setattr(module, "LOG", tmp_path / "log")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    (tmp_path / "complete").write_text("{}\n")

    def refuse(argv, **kwargs):
        raise AssertionError(f"nothing may run once complete, got {argv}")
    monkeypatch.setattr(module, "run", refuse)
    module.main()
    assert "not rebooting" in (tmp_path / "log").read_text()



# -- The carried repository must survive provisioning unchanged (2026-10-10 rehearsal) -----------------------

def _carried(tmp_path):
    import json
    import offline_cache
    root = tmp_path / "baseline-cache"
    (root / "apt").mkdir(parents=True)
    (root / "apt" / "Packages").write_text("Package: x\n")
    (root / "npm-cache").mkdir()
    (root / "npm-cache" / "index").write_text("tarball index\n")
    (root / "MANIFEST.json").write_text(json.dumps(offline_cache.build_manifest(root)))
    return root


def test_an_untouched_carried_repository_verifies_after_provisioning(tmp_path):
    assert _installer().verify_carried_repository(_carried(tmp_path)) == 2


def test_a_file_written_into_the_carried_repository_stops_the_install_by_name(tmp_path):
    """npm wrote npm-cache/_logs/<time>-debug-0.log into the repository during provisioning, so first boot later
    refused to trust it offline. The installer now catches that itself, naming the file."""
    root = _carried(tmp_path)
    (root / "npm-cache" / "_logs").mkdir()
    (root / "npm-cache" / "_logs" / "2026-10-10T09_24_43_216Z-debug-0.log").write_text("npm debug\n")
    with pytest.raises(RuntimeError, match="_logs/2026-10-10T09_24_43_216Z-debug-0.log"):
        _installer().verify_carried_repository(root)


def test_provision_gives_npm_a_scratch_copy_so_the_carried_cache_is_never_written():
    """npm writes into whatever cache it is given (a debug log on 2026-10-10, a rewritten cacache index entry on
    2026-10-11). Either breaks the carried repository's checksums, so npm only ever sees a scratch copy."""
    text = (REPO / "boot/provision.sh").read_text()
    line = next(l for l in text.splitlines() if "npm install -g --offline" in l)
    assert '--cache "$NPM_SCRATCH"' in line and "$BASELINE_PACKAGE_CACHE" not in line
    block = text[text.index("NPM_SCRATCH="):text.index(line) + 300]
    assert 'cp -a "$BASELINE_PACKAGE_CACHE/npm-cache" "$NPM_SCRATCH"' in block
    assert "--logs-dir /var/log/baseline-npm" in block
    assert 'rm -rf "$NPM_SCRATCH"' in text[text.index(line):text.index(line) + 1000]


def test_the_cache_also_carries_the_runtime_packages_the_applications_need():
    import application_bundle
    import offline_cache
    packages = offline_cache.required_packages(REPO)
    runtime = application_bundle.runtime_plan({"arch": "amd64", "os": "debian", "release": "13"})["packages"]
    for name in runtime:
        assert name in packages, name
    assert len(packages) == len(set(packages))


def _app_bundle(root, apps=("chrome", "spotify")):
    import hashlib
    import json
    for app in apps:
        folder = root / "apps" / app
        folder.mkdir(parents=True)
        data = f"payload of {app}".encode()
        (folder / "source.deb").write_bytes(data)
        (folder / "recipe.json").write_text(json.dumps({
            "app": app, "configuration": {}, "format": "baseline.application-build/v1",
            "platform": {"arch": "amd64", "os": "debian", "release": "13"},
            "source": {"medium": "deb", "package": app, "sha256": hashlib.sha256(data).hexdigest(),
                       "url": f"https://example.invalid/{app}.deb", "version": "1.0"}}))


def test_each_carried_application_is_checked_against_its_recipes_pinned_checksum(tmp_path):
    import offline_cache
    _app_bundle(tmp_path)
    report = offline_cache.verify_app_bundle(tmp_path, apps=("chrome", "spotify"))
    assert [r["app"] for r in report] == ["chrome", "spotify"] and report[0]["bytes"] == len(b"payload of chrome")
    (tmp_path / "apps/chrome/source.deb").write_bytes(b"tampered")
    with pytest.raises(RuntimeError):
        offline_cache.verify_app_bundle(tmp_path, apps=("chrome", "spotify"))


def test_a_missing_application_is_named_not_skipped(tmp_path):
    import offline_cache
    _app_bundle(tmp_path, apps=("chrome",))
    with pytest.raises(RuntimeError, match="spotify"):
        offline_cache.verify_app_bundle(tmp_path, apps=("chrome", "spotify"))


def test_the_drivers_the_catalog_declares_are_carried_too():
    import installer_cache
    import offline_cache
    names = installer_cache.firmware_packages()
    assert {"amd64-microcode", "intel-microcode", "firmware-realtek", "firmware-mediatek"} <= set(names)
    packages = offline_cache.required_packages(REPO)
    for name in names:
        assert name in packages, name


def test_a_rebuild_is_seeded_from_every_earlier_cache_without_duplicates(tmp_path):
    import offline_cache
    for folder, names in (("old/apt", ["a_1_amd64.deb", "b_1_amd64.deb"]), ("drive", ["b_1_amd64.deb", "c_1_all.deb"]),
                          ("flat", ["d_1_amd64.deb"])):
        (tmp_path / folder).mkdir(parents=True)
        for name in names:
            (tmp_path / folder / name).write_bytes(f"{folder}/{name}".encode())
    (tmp_path / "old/apt/notes.txt").write_text("not a package")
    seeds = offline_cache.seed_debs([tmp_path / "old", tmp_path / "drive", tmp_path / "flat", tmp_path / "missing"])
    assert [p.name for p in seeds] == ["a_1_amd64.deb", "b_1_amd64.deb", "c_1_all.deb", "d_1_amd64.deb"]
    assert (tmp_path / "old/apt/b_1_amd64.deb") in seeds          # the first seed that has a file wins
    assert offline_cache.seed_apps(tmp_path / "none", [tmp_path / "old"]) == []


def test_applications_already_prepared_in_a_seed_are_reused_not_downloaded_again(tmp_path):
    import offline_cache
    _app_bundle(tmp_path / "seed", apps=("chrome", "spotify"))
    target = tmp_path / "prepared"
    (target / "chrome").mkdir(parents=True)                       # already there: never touched
    (target / "chrome/recipe.json").write_text("{}")
    reused = offline_cache.seed_apps(target, [tmp_path / "seed"])
    assert reused == ["spotify"] and (target / "spotify/source.deb").is_file()
    assert (target / "chrome/recipe.json").read_text() == "{}"


# --- the child identity is carried into first boot, which sets the disk identifier before it records anything --------------

IDENTITY = {"uuid": "4af8c95a-fd01-271b-b1ae-f19827f945b7", "serial": "FD01N6557110C271B"}


def test_a_hook_without_an_identity_is_unchanged(tmp_path):
    hook = fbh.build_hook(REPO, tmp_path / "hook").read_text()
    assert "BASELINE_CHILD" not in hook and hook.rstrip().endswith('exec /usr/bin/python3 "$dest/baseline/bin/baseline-first-boot-install"')


def test_a_hook_with_an_identity_hands_it_to_the_installer_and_is_still_valid_shell(tmp_path):
    path = fbh.build_hook(REPO, tmp_path / "hook", child_identity=IDENTITY)
    last = path.read_text().rstrip().splitlines()[-1]
    assert last == ('exec env BASELINE_CHILD_UUID=4af8c95a-fd01-271b-b1ae-f19827f945b7 BASELINE_CHILD_SERIAL=FD01N6557110C271B '
                    '/usr/bin/python3 "$dest/baseline/bin/baseline-first-boot-install"')
    assert subprocess.run(["sh", "-n", str(path)], capture_output=True).returncode == 0
    assert path.stat().st_size < fbh.PROXMOX_HOOK_LIMIT


@pytest.mark.parametrize("identity", [
    {"uuid": "x; rm -rf /", "serial": "FD01N6557110C271B"},
    {"uuid": "4af8c95a-fd01-271b-b1ae-f19827f945b7", "serial": "bad serial; id"},
    {"uuid": "4af8c95a-fd01-271b-b1ae-f19827f945b7", "serial": "SHORT"},
    {"uuid": "4AF8C95A-FD01-271B-B1AE-F19827F945B7", "serial": "FD01N6557110C271B"},
    {"uuid": "4af8c95a-fd01-271b-b1ae-f19827f945b7"},
    {},
])
def test_an_identity_that_is_not_a_plain_uuid_and_serial_is_never_written_into_a_script(tmp_path, identity):
    with pytest.raises(fbh.HookError):
        fbh.build_hook(REPO, tmp_path / "hook", child_identity=identity)


def test_the_disk_carrying_the_serial_is_found_exactly_once():
    listing = "/dev/sda FD01N6557110C271B\n/dev/sdb MD89N41071210AP4E\n/dev/loop0 \n"
    assert _installer().disks_with_serial(listing, "FD01N6557110C271B") == ["/dev/sda"]
    assert _installer().disks_with_serial(listing, "NOT-THERE-1") == []
    assert _installer().disks_with_serial(listing + "/dev/sdc FD01N6557110C271B\n", "FD01N6557110C271B") == ["/dev/sda", "/dev/sdc"]


def test_first_boot_sets_the_identifier_on_the_one_disk_with_that_serial_before_anything_else(tmp_path, monkeypatch):
    installer = _installer()
    calls = []
    monkeypatch.setenv("BASELINE_CHILD_UUID", IDENTITY["uuid"])
    monkeypatch.setenv("BASELINE_CHILD_SERIAL", IDENTITY["serial"])
    monkeypatch.setattr(installer, "STATE", tmp_path / "state")
    monkeypatch.setattr(installer, "LOG", tmp_path / "log")
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(installer, "list_disks", lambda: "/dev/sda FD01N6557110C271B\n/dev/sdb MD89N41071210AP4E\n")
    host_file = tmp_path / "etc" / "host-id"
    installer.step_identity(ensure=lambda device, wanted: calls.append((device, wanted)), host_id_path=host_file)
    assert calls == [("/dev/sda", IDENTITY["uuid"])]
    assert host_file.read_text() == IDENTITY["uuid"] + "\n"        # the backbone reference components read
    assert [name for name, _ in installer.STEPS][:3] == ["identity", "volume-group", "storage"]   # the group is named before any role volume is mounted


def test_first_boot_refuses_when_the_serial_is_on_no_disk_or_on_two(tmp_path, monkeypatch):
    installer = _installer()
    monkeypatch.setenv("BASELINE_CHILD_UUID", IDENTITY["uuid"])
    monkeypatch.setenv("BASELINE_CHILD_SERIAL", IDENTITY["serial"])
    monkeypatch.setattr(installer, "STATE", tmp_path)
    monkeypatch.setattr(installer, "LOG", tmp_path / "log")
    for listing in ("/dev/sdb MD89N41071210AP4E\n", "/dev/sda FD01N6557110C271B\n/dev/sdc FD01N6557110C271B\n"):
        monkeypatch.setattr(installer, "list_disks", lambda l=listing: l)
        with pytest.raises(RuntimeError):
            installer.step_identity(ensure=lambda *a: None, host_id_path=tmp_path / "host-id")
    assert not (tmp_path / "host-id").exists()


def test_first_boot_without_a_carried_identity_leaves_the_disk_identifier_alone(tmp_path, monkeypatch):
    installer = _installer()
    monkeypatch.delenv("BASELINE_CHILD_UUID", raising=False)
    monkeypatch.delenv("BASELINE_CHILD_SERIAL", raising=False)
    monkeypatch.setattr(installer, "STATE", tmp_path)
    monkeypatch.setattr(installer, "LOG", tmp_path / "log")
    called = []
    installer.step_identity(ensure=lambda *a: called.append(a))
    assert called == []


def test_first_boot_records_the_machine_and_links_the_storage_roles_after_storage(tmp_path, monkeypatch):
    import identifiers as idn
    installer = _installer()
    monkeypatch.setattr(installer, "STATE", tmp_path / "state")
    monkeypatch.setattr(installer, "LOG", tmp_path / "log")
    (tmp_path / "state").mkdir()
    names = [name for name, _ in installer.STEPS]
    assert names.index("storage") < names.index("machine") < names.index("installer")
    host = idn.host_id("4af8c95a-1c9b-437a-a306-c53855d4077f", IDENTITY["serial"])
    idn.register_host(host, serial=IDENTITY["serial"])
    (tmp_path / "host-id").write_text(host + "\n")
    root = tmp_path / "root"
    (root / "sys/class/dmi/id").mkdir(parents=True)
    (root / "sys/class/dmi/id/product_uuid").write_text("11111111-2222-4333-8444-555555555555\n")
    import machine_context
    installer.step_machine(host_id_path=tmp_path / "host-id", read=machine_context.file_reader(str(root)))
    assert len(machine_context.load_profiles()) == 1


def test_first_boot_without_a_host_identifier_skips_the_machine_record_without_failing(tmp_path, monkeypatch):
    installer = _installer()
    monkeypatch.setattr(installer, "STATE", tmp_path / "state")
    monkeypatch.setattr(installer, "LOG", tmp_path / "log")
    (tmp_path / "state").mkdir()
    installer.step_machine(host_id_path=tmp_path / "absent")


def test_first_boot_stores_a_carried_development_user_root_only_and_does_nothing_without_one(tmp_path, monkeypatch):
    installer = _installer()
    monkeypatch.setattr(installer, "STATE", tmp_path / "state")
    monkeypatch.setattr(installer, "LOG", tmp_path / "log")
    (tmp_path / "state").mkdir()
    monkeypatch.delenv("BASELINE_DEV_USER", raising=False)
    installer.step_dev_user(write_to=tmp_path / "none", systemd=False)
    assert not (tmp_path / "none").exists()
    value = "baseline:$6$abcdefgh$" + "A" * 86
    monkeypatch.setenv("BASELINE_DEV_USER", value)
    installer.step_dev_user(write_to=tmp_path / "etc" / "dev-user.hash", systemd=False)
    stored = tmp_path / "etc" / "dev-user.hash"
    assert stored.read_text() == value + "\n" and stored.stat().st_mode & 0o777 == 0o600
    assert [n for n, _ in installer.STEPS][-1] == "dev-user"


def test_the_hook_carries_a_development_user_only_if_it_is_a_name_and_a_sha512crypt_hash(tmp_path):
    import first_boot_hook as fbh
    import pytest
    good = "baseline:$6$abcdefgh$" + "A" * 86
    line = fbh._exec_line(None, good)
    assert line.startswith("exec env BASELINE_DEV_USER='baseline:$6$abcdefgh$") and line.endswith('"')
    assert "BASELINE_DEV_USER" not in fbh._exec_line(None, None)
    both = fbh._exec_line({"uuid": "4af8c95a-fd01-271b-10be-bc48c28f0a00", "serial": "FD01N6557110C271B"}, good)
    assert "BASELINE_CHILD_UUID=" in both and "BASELINE_DEV_USER='" in both
    for bad in ("baseline:CTEST1!", "Bad:" + good.split(":", 1)[1], good + "'; rm -rf /", "baseline:$6$x$short", ""):
        with pytest.raises(fbh.HookError):
            fbh._exec_line(None, bad)


def test_the_installer_cache_storage_is_named_for_the_volume_and_the_old_name_is_replaced(tmp_path, monkeypatch):
    """Operator, 2026-10-12: `baseline-isos` is not a volume. The same folder is registered as `installer-cache`, the old entry removed."""
    import json
    import os_isos
    installer = _installer()
    root = tmp_path / "INSTALLER_CACHE"
    (root / "isos").mkdir(parents=True)
    monkeypatch.setattr(installer, "OS_ISOS", root / "isos")
    monkeypatch.setattr(installer, "LOG", tmp_path / "log")
    commands = []
    monkeypatch.setattr(installer, "run", lambda argv, **kw: commands.append(list(argv)))
    listing = json.dumps([{"storage": "baseline-isos", "type": "dir", "path": str(root)}])
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: __import__("subprocess").CompletedProcess(a, 0, listing, ""))
    installer.register_iso_storage()
    assert os_isos.ISO_STORAGE == "installer-cache"
    assert commands[0] == ["pvesm", "remove", "baseline-isos"]
    assert commands[1][:4] == ["pvesm", "add", "dir", "installer-cache"] and str(root) in commands[1]


GOOD_LIST = '{"os": [{"id": "debian", "name": "Debian 13", "iso": "debian.iso"}]}'


def _os_list_step(tmp_path, monkeypatch, *, source_text=None, host_text=None):
    installer = _installer()
    marks = []
    monkeypatch.setattr(installer, "mark", lambda step, **facts: marks.append((step, facts)))
    monkeypatch.setattr(installer, "log", lambda *a, **k: None)
    source, dest = tmp_path / "media" / "supported-os.json", tmp_path / "USER_ADMIN" / "config" / "supported-os.json"
    if source_text is not None:
        source.parent.mkdir(parents=True)
        source.write_text(source_text)
    if host_text is not None:
        dest.parent.mkdir(parents=True)
        dest.write_text(host_text)
    installer.step_os_list(source=source, dest=dest)
    return dest, marks


def test_the_list_on_the_installer_media_is_carried_to_user_admin(tmp_path, monkeypatch):
    dest, marks = _os_list_step(tmp_path, monkeypatch, source_text=GOOD_LIST)
    assert dest.read_text() == GOOD_LIST and marks == [("os-list", {"result": "carried", "entries": 1})]
    assert not dest.with_name(dest.name + ".part").exists()


def test_a_list_the_host_already_has_is_never_overwritten(tmp_path, monkeypatch):
    dest, marks = _os_list_step(tmp_path, monkeypatch, source_text=GOOD_LIST, host_text='{"os": []}')
    assert dest.read_text() == '{"os": []}' and marks[0][1]["result"] == "kept the host's own"


def test_a_bad_list_is_not_carried_and_does_not_stop_the_installation(tmp_path, monkeypatch):
    dest, marks = _os_list_step(tmp_path, monkeypatch, source_text='{"os": [{"id": "Bad Id"}]}')
    assert not dest.exists() and marks[0][1]["result"].startswith("refused")


def test_no_list_on_the_media_is_recorded_not_an_error(tmp_path, monkeypatch):
    dest, marks = _os_list_step(tmp_path, monkeypatch)
    assert not dest.exists() and marks[0][1]["result"] == "none carried"


def test_the_list_step_runs_before_provisioning_and_the_dev_user_stays_last():
    names = [n for n, _ in _installer().STEPS]
    assert names.index("os-isos") < names.index("os-list") < names.index("provision") and names[-1] == "dev-user"
