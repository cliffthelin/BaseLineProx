"""Unit tests for appdata.py - per-application isolation, registry,
access and data (direct instruction, 2026-09-30: "Each application
should have its own isolation and registry and access and data",
scope "anything installable that is not a driver", mechanism
"overlays for each that puts its data here").

Pure planning: nothing here mounts, chowns or writes. Each of the four
guarantees the instruction named is asserted directly rather than
described in a comment.
"""
import appdata
import installer_cache as ic


# -- Scope: installable, not a driver ----------------------------------

def test_no_driver_or_firmware_is_treated_as_an_application():
    """The instruction excludes drivers explicitly: firmware belongs to
    hardware, not to a person, and has no personal data."""
    app_ids = {a.app_id for a in appdata.installable_apps()}
    for entry in ic.catalog():
        if entry.kind == ic.KIND_FIRMWARE:
            assert entry.entry_id not in app_ids, f"{entry.entry_id} is a driver"


def test_the_substrate_iso_is_not_an_application():
    """Proxmox VE is the substrate the apps run on, not an app on it."""
    assert "proxmox-ve-source" not in {a.app_id for a in appdata.installable_apps()}


def test_every_installable_package_and_guest_is_an_application():
    app_ids = {a.app_id for a in appdata.installable_apps()}
    for entry in ic.catalog():
        if entry.kind in (ic.KIND_PACKAGE, ic.KIND_SCRIPT):
            assert entry.entry_id in app_ids


def test_apps_are_derived_from_the_installer_catalog_so_they_cannot_drift():
    catalog_ids = {e.entry_id for e in ic.catalog()}
    assert {a.app_id for a in appdata.installable_apps()} <= catalog_ids


def test_both_vm_lxc_guests_and_packages_are_represented():
    kinds = {a.kind for a in appdata.installable_apps()}
    assert appdata.KIND_PACKAGE in kinds
    assert appdata.KIND_GUEST in kinds


# -- Data: AppData volume and nowhere else -----------------------------

def test_appdata_is_per_persona_not_one_shared_store():
    """Phone-OS model: app data belongs to a person."""
    assert appdata.appdata_root("admin") != appdata.appdata_root("personal")
    assert appdata.appdata_root("personal").endswith("APPDATA_PERSONAL")


def test_every_apps_data_lives_under_its_own_appdata_home():
    for plan in appdata.plan_all("personal"):
        assert plan.home.startswith(appdata.appdata_root("personal") + "/")
        for overlay in plan.overlays:
            assert overlay.upperdir.startswith(plan.home + "/")
            assert overlay.workdir.startswith(plan.home + "/")


def test_no_app_writes_outside_appdata():
    """The whole rule in one assertion: no writable layer anywhere may
    sit outside the AppData volume."""
    root = appdata.appdata_root("personal")
    for plan in appdata.plan_all("personal"):
        for overlay in plan.overlays:
            assert overlay.upperdir.startswith(root)
            assert overlay.workdir.startswith(root)


def test_appdata_never_lands_on_the_shared_baseline_volume():
    for plan in appdata.plan_all("personal"):
        assert "/mnt/BASELINE" not in plan.home
        assert "/mnt/BASELINE" not in plan.registry_db


# -- Registry: its own, not a shared one -------------------------------

def test_each_app_has_its_own_registry_database():
    plans = appdata.plan_all("personal")
    dbs = [p.registry_db for p in plans]
    assert len(dbs) == len(set(dbs)), "two apps share a registry database"


def test_an_apps_registry_lives_inside_its_own_tree():
    for plan in appdata.plan_all("personal"):
        assert plan.registry_db.startswith(plan.home + "/")


def test_registry_path_is_per_persona_and_per_app():
    a = appdata.registry_path("admin", "chromium")
    b = appdata.registry_path("personal", "chromium")
    c = appdata.registry_path("personal", "podman")
    assert a != b != c and a != c


# -- Access: its own ---------------------------------------------------

def test_each_app_has_its_own_owner_identity():
    plans = appdata.plan_all("personal")
    owners = [p.owner_user for p in plans]
    assert len(owners) == len(set(owners)), "two apps share an owner"


def test_appdata_is_not_group_or_world_readable():
    for plan in appdata.plan_all("personal"):
        assert plan.mode == "0700"


# -- Isolation ---------------------------------------------------------

def test_no_apps_writable_layer_falls_inside_another_apps_tree():
    """Qubes-style: isolation is the guarantee, so it is checked, not
    assumed."""
    assert appdata.cross_app_leaks(appdata.plan_all("personal")) == []


def test_every_plan_satisfies_the_full_isolation_contract():
    for plan in appdata.plan_all("personal"):
        assert plan.isolated, f"{plan.app.app_id} fails the isolation contract"


# -- Overlays ----------------------------------------------------------

def test_the_immutable_base_is_the_lowerdir_and_is_never_written_to():
    """NixOS-style: the installed base is read-only; every write goes to
    the upper layer on AppData."""
    plan = appdata.plan_for("personal", _app("pihole-lxc"))
    overlay = plan.overlays[0]
    assert overlay.lowerdir == overlay.target
    assert not overlay.lowerdir.startswith(plan.home)
    assert overlay.upperdir.startswith(plan.home)


def test_overlay_mounts_back_at_the_path_the_app_already_uses():
    """The app needs no cooperation - it writes where it always did.
    For a guest that is its own per-VMID disk, not the shared store."""
    plan = appdata.plan_for("personal", _app("pihole-lxc"))
    assert plan.overlays[0].target == "/var/lib/vz/private/pihole-lxc"


def test_mount_argv_is_a_real_overlay_invocation():
    plan = appdata.plan_for("personal", _app("chromium"))
    argv = plan.overlays[0].mount_argv()
    assert argv[:4] == ["mount", "-t", "overlay", "overlay"]
    opts = argv[argv.index("-o") + 1]
    assert "lowerdir=" in opts and "upperdir=" in opts and "workdir=" in opts
    assert argv[-1] == plan.overlays[0].target


def test_each_data_target_gets_its_own_upper_and_work_pair():
    plan = appdata.plan_for("personal", _app("chromium"))
    assert len(plan.overlays) == 2            # config and cache
    uppers = {o.upperdir for o in plan.overlays}
    works = {o.workdir for o in plan.overlays}
    assert len(uppers) == 2 and len(works) == 2
    assert not (uppers & works)


def test_workdir_shares_the_filesystem_with_upperdir_as_overlayfs_requires():
    for plan in appdata.plan_all("personal"):
        for overlay in plan.overlays:
            assert overlay.workdir.startswith(plan.home)
            assert overlay.upperdir.startswith(plan.home)


def test_an_app_with_no_persistent_data_gets_no_overlay_and_says_so():
    """A library or one-shot tool genuinely has no personal data. That
    is recorded explicitly, never guessed into an overlay."""
    plan = appdata.plan_for("personal", _app("python3-rich"))
    assert plan.overlays == []
    assert plan.app.has_persistent_data is False


def test_an_app_with_persistent_data_reports_that_it_has_some():
    assert _app("gnupg").has_persistent_data is True


def test_required_directories_cover_every_upper_and_work_path():
    plan = appdata.plan_for("personal", _app("chromium"))
    dirs = appdata.required_directories(plan)
    for overlay in plan.overlays:
        assert overlay.upperdir in dirs
        assert overlay.workdir in dirs
    assert plan.home in dirs


# -- Volume naming -----------------------------------------------------

def test_appdata_volume_names_follow_the_existing_persona_convention():
    assert appdata.appdata_label("personal") == "APPDATA_PERSONAL"
    assert appdata.appdata_lv_name("personal") == "baseline_appdata_personal"


def _app(app_id):
    return next(a for a in appdata.installable_apps() if a.app_id == app_id)


def test_no_two_applications_overlay_the_same_target():
    """Real defect this caught: every LXC guest originally targeted
    /var/lib/vz/private, so four overlays would have contended for one
    mount point - the second hiding the first and the guests silently
    sharing data. Upperdir separation does not prevent that; the target
    has to be distinct too."""
    assert appdata.target_conflicts(appdata.plan_all("personal")) == []


def test_each_guest_targets_its_own_disk_not_the_shared_proxmox_store():
    for plan in appdata.plan_all("personal"):
        if plan.app.kind != appdata.KIND_GUEST:
            continue
        for overlay in plan.overlays:
            assert overlay.target not in ("/var/lib/vz/private", "/var/lib/vz/images"), (
                f"{plan.app.app_id} targets the shared Proxmox store")
            assert plan.app.app_id in overlay.target
