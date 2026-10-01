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


# -- Package formats (Flatpak / Snap / AppImage) -----------------------

def test_every_supported_format_declares_its_isolation_honestly():
    for fmt in appdata.supported_formats():
        assert fmt.isolation_mechanism.strip()
        assert fmt.baseline_must_supply, f"{fmt.format_id} claims nothing is needed"


def test_formats_that_already_sandbox_are_not_sandboxed_again():
    """The governing rule: never duplicate a sandbox that exists.
    Two permission models that can disagree is worse than one."""
    for kind in (appdata.KIND_FLATPAK, appdata.KIND_SNAP):
        fmt = appdata.format_for(kind)
        assert fmt.brings_own_sandbox is True
        assert "sandbox" not in " ".join(fmt.baseline_must_supply).lower()


def test_appimage_is_flagged_as_bringing_no_isolation_at_all():
    """AppImage has no manifest, no install step and no confinement, so
    Baseline must supply all of it - the format where this module
    carries the most weight."""
    fmt = appdata.format_for(appdata.KIND_APPIMAGE)
    assert fmt.brings_own_sandbox is False
    assert "sandbox" in " ".join(fmt.baseline_must_supply).lower()
    assert "app identity" in fmt.baseline_must_supply


def test_confinement_gap_is_smaller_for_a_sandboxed_format():
    assert len(appdata.confinement_gap(appdata.KIND_FLATPAK)) < \
           len(appdata.confinement_gap(appdata.KIND_APPIMAGE))


def test_flatpak_uses_its_own_per_app_data_convention():
    fmt = appdata.format_for(appdata.KIND_FLATPAK)
    assert fmt.data_root("org.mozilla.firefox") == "~/.var/app/org.mozilla.firefox"


def test_snap_targets_current_so_it_survives_a_revision_bump():
    """Snap data is revision-numbered; `current` is the stable symlink."""
    assert appdata.format_for(appdata.KIND_SNAP).data_root("firefox").endswith("/current")


def test_a_formats_own_data_root_is_what_gets_overlaid():
    """Baseline follows the format's layout instead of imposing a second
    one beside it - otherwise the app keeps writing where it always did
    and the overlay captures nothing."""
    app = appdata.AppSpec("org.mozilla.firefox", "Firefox", appdata.KIND_FLATPAK,
                          source="flathub")
    plan = appdata.plan_for("personal", app)
    assert len(plan.overlays) == 1
    assert plan.overlays[0].target == "~/.var/app/org.mozilla.firefox"
    assert plan.overlays[0].upperdir.startswith(plan.home)


def test_a_flatpak_app_still_gets_its_own_registry_and_owner():
    app = appdata.AppSpec("org.mozilla.firefox", "Firefox", appdata.KIND_FLATPAK,
                          source="flathub")
    plan = appdata.plan_for("personal", app)
    assert plan.registry_db.startswith(plan.home)
    assert plan.mode == "0700"
    assert plan.isolated


def test_flatpak_records_its_conflict_with_the_declined_portal_decision():
    """milestone-2-gui-plan.md declined xdg-desktop-portal on trust-model
    grounds. Flatpak's permissions depend on it, so adopting Flatpak
    reopens that decision - recorded, not silently assumed away."""
    fmt = appdata.format_for(appdata.KIND_FLATPAK)
    assert "xdg-desktop-portal" in fmt.requires
    assert "portal" in fmt.notes.lower()


# -- Containers: binds, digest pinning, quadlet wiring -----------------

def test_caddy_is_a_container_application():
    assert _app("caddy").kind == appdata.KIND_CONTAINER


def test_a_container_gets_bind_mounts_not_host_overlays():
    """/data exists only inside the container's mount namespace - a host
    overlay at /data would capture nothing the container writes."""
    plan = appdata.plan_for("personal", _app("caddy"))
    assert plan.overlays == []
    assert {b.container for b in plan.binds} == {"/data", "/config", "/etc/caddy"}


def test_every_container_bind_comes_from_the_apps_own_appdata_home():
    plan = appdata.plan_for("personal", _app("caddy"))
    for bind in plan.binds:
        assert bind.host.startswith(plan.home + "/binds/")
    assert plan.isolated


def test_the_caddyfile_is_bound_read_only_so_caddy_cannot_rewrite_its_routing():
    plan = appdata.plan_for("personal", _app("caddy"))
    etc = next(b for b in plan.binds if b.container == "/etc/caddy")
    assert etc.read_only is True
    assert etc.volume_arg().endswith(":/etc/caddy:ro")


def test_container_spec_pulls_by_digest_runs_rootless_as_the_apps_own_user():
    plan = appdata.plan_for("personal", _app("caddy"))
    spec = appdata.container_spec(plan)
    assert "@sha256:" in spec.image
    assert spec.rootless is True
    assert spec.user == plan.owner_user
    assert all(v.split(":")[0].startswith(plan.home) for v in spec.volumes)


def test_container_spec_refuses_an_unpinned_image_rather_than_using_a_tag():
    import pytest
    app = appdata.AppSpec("x", "x", appdata.KIND_CONTAINER, source="s",
                          image_ref="quay.io/x/y:latest")
    with pytest.raises(appdata.UnpinnedImage):
        appdata.container_spec(appdata.plan_for("personal", app))


def test_caddys_admin_port_is_never_published():
    plan = appdata.plan_for("personal", _app("caddy"))
    for port in appdata.CONTAINER_NEVER_PUBLISH["caddy"]:
        assert port not in appdata.published_ports(plan)


def test_container_spec_renders_a_real_quadlet_unit():
    import quadlet
    unit = quadlet.generate_unit(appdata.container_spec(appdata.plan_for("personal", _app("caddy"))))
    assert "Image=quay.io/hummingbird/caddy@sha256:" in unit
    assert "PublishPort=8443:8443" in unit
    assert "2019" not in unit
    assert ":/etc/caddy:ro" in unit


def test_two_containers_may_share_an_internal_path_without_conflict():
    """Separate mount namespaces: two containers each using /data is not
    the target collision that broke the LXC guests."""
    plans = appdata.plan_all("personal")
    assert appdata.target_conflicts(plans) == []
    assert appdata.cross_app_leaks(plans) == []


def test_container_bind_directories_are_created_with_the_plan():
    plan = appdata.plan_for("personal", _app("caddy"))
    dirs = appdata.required_directories(plan)
    for bind in plan.binds:
        assert bind.host in dirs
