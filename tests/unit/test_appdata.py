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


def test_every_installable_package_is_an_application():
    app_ids = {a.app_id for a in appdata.installable_apps()}
    for entry in ic.catalog():
        if entry.kind == ic.KIND_PACKAGE:
            assert entry.entry_id in app_ids


def test_apps_are_derived_from_the_installer_catalog_so_they_cannot_drift():
    catalog_ids = {e.entry_id for e in ic.catalog()}
    assert {a.app_id for a in appdata.installable_apps()} <= catalog_ids


def test_packages_and_containers_are_represented():
    kinds = {a.kind for a in appdata.installable_apps()}
    assert appdata.KIND_PACKAGE in kinds
    assert appdata.KIND_CONTAINER in kinds


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
    a = appdata.registry_path("admin", "A_D_00001")
    b = appdata.registry_path("personal", "A_D_00001")
    c = appdata.registry_path("personal", "A_D_00002")
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
    plan = _plan("chromium")
    overlay = plan.overlays[0]
    assert overlay.lowerdir == overlay.target
    assert not overlay.lowerdir.startswith(plan.home)
    assert overlay.upperdir.startswith(plan.home)


def test_overlay_mounts_back_at_the_path_the_app_already_uses():
    """The app needs no cooperation - it writes where it always did.
    """
    plan = _plan("chromium")
    assert plan.overlays[0].target == "~/.config/chromium"


def test_mount_argv_is_a_real_overlay_invocation():
    plan = _plan("chromium")
    argv = plan.overlays[0].mount_argv()
    assert argv[:4] == ["mount", "-t", "overlay", "overlay"]
    opts = argv[argv.index("-o") + 1]
    assert "lowerdir=" in opts and "upperdir=" in opts and "workdir=" in opts
    assert argv[-1] == plan.overlays[0].target


def test_each_data_target_gets_its_own_upper_and_work_pair():
    plan = _plan("chromium")
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
    plan = _plan("python3-rich")
    assert plan.overlays == []
    assert plan.app.has_persistent_data is False


def test_an_app_with_persistent_data_reports_that_it_has_some():
    assert _app("gnupg").has_persistent_data is True


def test_required_directories_cover_every_upper_and_work_path():
    plan = _plan("chromium")
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


def _plan(app_id, persona="personal"):
    return next(p for p in appdata.plan_all(persona) if p.app.app_id == app_id)


def _assign(app, code="00099"):
    import naming
    return naming.Assignment(naming.format_id("A", app.medium.letter, code), False)


def test_no_two_applications_overlay_the_same_target():
    """Real defect this caught (back when LXCs were planned here): several
    apps targeted one shared path, so their overlays contended for one
    mount point and silently shared data. Upperdir separation does not
    prevent that; the target has to be distinct too."""
    assert appdata.target_conflicts(appdata.plan_all("personal")) == []


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
    plan = appdata.plan_for("personal", app, _assign(app))
    assert len(plan.overlays) == 1
    assert plan.overlays[0].target == "~/.var/app/org.mozilla.firefox"
    assert plan.overlays[0].upperdir.startswith(plan.home)


def test_a_flatpak_app_still_gets_its_own_registry_and_owner():
    app = appdata.AppSpec("org.mozilla.firefox", "Firefox", appdata.KIND_FLATPAK,
                          source="flathub")
    plan = appdata.plan_for("personal", app, _assign(app))
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
    plan = _plan("caddy")
    assert plan.overlays == []
    assert {b.container for b in plan.binds} == {"/data", "/config", "/etc/caddy"}


def test_every_container_bind_comes_from_the_apps_own_appdata_home():
    plan = _plan("caddy")
    for bind in plan.binds:
        assert bind.host.startswith(plan.home + "/binds/")
    assert plan.isolated


def test_the_caddyfile_is_bound_read_only_so_caddy_cannot_rewrite_its_routing():
    plan = _plan("caddy")
    etc = next(b for b in plan.binds if b.container == "/etc/caddy")
    assert etc.read_only is True
    assert etc.volume_arg().endswith(":/etc/caddy:ro")


def test_container_spec_pulls_by_digest_runs_rootless_as_the_apps_own_user():
    plan = _plan("caddy")
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
        appdata.container_spec(appdata.plan_for("personal", app, _assign(app)))


def test_caddys_admin_port_is_never_published():
    plan = _plan("caddy")
    for port in appdata.CONTAINER_NEVER_PUBLISH["caddy"]:
        assert port not in appdata.published_ports(plan)


def test_container_spec_renders_a_real_quadlet_unit():
    import quadlet
    unit = quadlet.generate_unit(appdata.container_spec(_plan("caddy")))
    assert "Image=quay.io/hummingbird/caddy@sha256:" in unit
    assert "PublishPort=8443:8443" in unit
    assert "2019" not in unit
    assert ":/etc/caddy:ro" in unit


def test_two_containers_may_share_an_internal_path_without_conflict():
    """Separate mount namespaces: two containers each using /data is not
    the target collision that once broke overlapping targets."""
    plans = appdata.plan_all("personal")
    assert appdata.target_conflicts(plans) == []
    assert appdata.cross_app_leaks(plans) == []


def test_container_bind_directories_are_created_with_the_plan():
    plan = _plan("caddy")
    dirs = appdata.required_directories(plan)
    for bind in plan.binds:
        assert bind.host in dirs


# -- Medium contracts --------------------------------------------------

def test_every_app_medium_in_naming_has_a_contract():
    """ISO is an operating-system image, not an application medium."""
    import naming
    letters = {m.letter for m in appdata.MEDIA.values()}
    # ISO is an OS image; L (LXC) and V (VM) live on
    # INSTALLER_CACHE rather than in per-persona AppData.
    assert letters == set(naming.MEDIA) - {"I", "L", "V"}


def test_every_contract_states_its_method_of_use_and_status():
    statuses = {appdata.MVP_COMPLETED, appdata.IN_PROGRESS, appdata.ON_ROADMAP, appdata.IN_DISCOVERY}
    for m in appdata.MEDIA.values():
        assert m.method_of_use.strip(), m.name
        assert m.status in statuses, m.name


def test_every_named_helper_is_real_code():
    """A contract may not cite a helper that does not exist."""
    import importlib
    for m in appdata.MEDIA.values():
        for ref in m.helpers:
            module, _, attr = ref.partition(".")
            mod = importlib.import_module(module)
            if attr:
                assert getattr(mod, attr, None) is not None, f"{m.name}: {ref} does not exist"


def test_a_medium_with_no_helper_does_not_claim_to_be_working():
    for m in appdata.MEDIA.values():
        if not m.helpers:
            assert m.status in (appdata.ON_ROADMAP, appdata.IN_DISCOVERY), m.name


def test_each_medium_stands_alone_one_letter_per_kind():
    letters = [m.letter for m in appdata.MEDIA.values()]
    assert len(letters) == len(set(letters))



# -- Identifiers -------------------------------------------------------

def test_every_home_is_keyed_by_its_identifier_not_its_name():
    for plan in appdata.plan_all("personal"):
        assert plan.home == f"/mnt/APPDATA_PERSONAL/{plan.baseline_id}"
        assert plan.app.app_id not in plan.home


def test_identifiers_match_the_apps_medium_and_the_app_cluster():
    import naming
    for plan in appdata.plan_all("personal"):
        parsed = naming.parse_id(plan.baseline_id)
        assert parsed.cluster == "A"
        assert parsed.medium == plan.app.medium.letter


def test_no_two_apps_share_an_identifier():
    assert appdata.identifier_collisions(appdata.plan_all("personal")) == []


def test_the_owner_uid_comes_from_the_identifier():
    plan = _plan("caddy")
    assert plan.owner_user == f"baseline-{plan.baseline_id.lower()}"


def test_the_name_is_only_an_alias_under_by_name():
    plan = _plan("caddy")
    assert plan.alias.link == "/mnt/APPDATA_PERSONAL/by-name/caddy"
    assert plan.alias.target == f"../{plan.baseline_id}"


def test_no_mount_path_goes_through_an_alias():
    import naming
    for plan in appdata.plan_all("personal"):
        for path in [plan.home] + [o.upperdir for o in plan.overlays] + [b.host for b in plan.binds]:
            assert naming.ALIAS_DIRNAME not in path.split("/")


def test_an_identifier_for_the_wrong_medium_is_refused():
    import naming
    import pytest
    with pytest.raises(naming.NamingError):
        appdata.plan_for("personal", _app("caddy"), naming.Assignment("A_D_00001", True))


def test_without_allocations_identifiers_are_previews_and_say_so():
    assert all(p.id_allocated is False for p in appdata.plan_all("personal"))


def test_allocated_identifiers_are_used_and_marked_allocated():
    import naming
    naming.allocate_many(appdata.id_requests())
    plans = appdata.plan_all("personal")
    assert all(p.id_allocated for p in plans)
    assert _plan("caddy").baseline_id == naming.find("A", "C", "caddy")


def test_planning_never_creates_the_registry(tmp_path, monkeypatch):
    """Viewing plans must not write a database onto an unmounted volume path."""
    import registry
    db = tmp_path / "none" / "foundation.db"
    monkeypatch.setattr(registry, "GLOBAL_DB_PATH", str(db))
    appdata.plan_all("personal")
    assert not db.parent.exists()


def test_the_same_app_has_the_same_identifier_in_every_persona():
    admin = {p.app.app_id: p.baseline_id for p in appdata.plan_all("admin")}
    personal = {p.app.app_id: p.baseline_id for p in appdata.plan_all("personal")}
    assert admin == personal


def test_container_spec_volumes_are_all_persistent():
    import quadlet
    plans = [p for p in appdata.plan_all("personal") if p.app.kind == appdata.KIND_CONTAINER]
    assert plans
    for plan in plans:
        assert quadlet.non_persistent_volumes(appdata.container_spec(plan)) == []


def test_vms_and_lxcs_are_not_persona_appdata():
    """VM/LXC state is install-wide and lives on BASELINE, with Proxmox only
    needing to reach it (master PRD §3); installers live on INSTALLER_CACHE.
    Neither is per-persona AppData."""
    import installer_cache as ic
    vm_lxc_ids = {e.entry_id for e in ic.catalog() if e.kind == ic.KIND_SCRIPT}
    assert vm_lxc_ids, "the catalog should still list VM/LXC installers"
    assert not (vm_lxc_ids & {a.app_id for a in appdata.installable_apps()})
    assert not hasattr(appdata, "KIND_LXC") and not hasattr(appdata, "KIND_VM")
