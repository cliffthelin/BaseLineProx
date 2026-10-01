"""Unit tests for installer_cache.py - the INSTALLER_CACHE transparency
report (direct instruction, 2026-09-30: show all software, packages, OS
distros and drivers with their original installer, what is on the volume
now, and what a self-replicating build would need).

No real volume is ever read - FakeRunner supplies real `findmnt`/`ls -lA`
output shapes.
"""
from fake_runner import FakeProc, FakeRunner

import installer_cache as ic

ISOS_LS = (
    "total 27803588\n"
    "-rw-rw-r-- 1 cane cane 1706178560 proxmox-ve-source.iso\n"
    "-rw-rw-r-- 1 cane cane 6185304064 omarchy-4.0.4.iso\n"
    "drwxrwxr-x 2 cane cane       4096 nested-dir\n"
)
PACKAGES_LS = (
    "total 400\n"
    "-rw-rw-r-- 1 cane cane 204800 ethtool_6.10-1_amd64.deb\n"
    "-rw-rw-r-- 1 cane cane 102400 nvme-cli_2.8-1_amd64.deb\n"
)


def _runner(*, mounted=True, isos=ISOS_LS, packages=PACKAGES_LS):
    findmnt = FakeProc(0, "/dev/sdd2 ext4\n") if mounted else FakeProc(1, "")
    return FakeRunner(command_responses=[
        (lambda a: a[:1] == ["findmnt"], findmnt),
        (lambda a: a[:1] == ["ls"] and a[-1].endswith("/isos"), FakeProc(0, isos)),
        (lambda a: a[:1] == ["ls"] and a[-1].endswith("/packages"), FakeProc(0, packages)),
        (lambda a: a[:1] == ["ls"], FakeProc(0, "total 0\n")),
    ])


# -- Catalog -----------------------------------------------------------

def test_catalog_covers_every_kind_the_instruction_named():
    kinds = {e.kind for e in ic.catalog()}
    assert kinds == {ic.KIND_ISO, ic.KIND_PACKAGE, ic.KIND_FIRMWARE, ic.KIND_SCRIPT, ic.KIND_IMAGE}


def test_every_catalog_entry_names_a_real_origin_helper_and_config():
    """The instruction: each artifact must have an associated install
    helper and/or configuration. An entry missing any of the three is a
    gap in the build story, so none may be blank."""
    for entry in ic.catalog():
        assert entry.origin.strip(), f"{entry.entry_id} has no origin"
        assert entry.install_helper.strip(), f"{entry.entry_id} has no install helper"
        assert entry.config_section.strip(), f"{entry.entry_id} has no config section"


def test_catalog_includes_the_proxmox_source_iso():
    ids = {e.entry_id for e in ic.catalog()}
    assert "proxmox-ve-source" in ids


def test_catalog_derives_diagnostic_packages_from_the_module_that_owns_them():
    import firstboot_statemachine as fsm
    ids = {e.entry_id for e in ic.catalog()}
    for pkg in fsm.DIAGNOSTIC_PACKAGES:
        assert pkg in ids, f"{pkg} is installed at firstboot but absent from the catalog"


def test_catalog_derives_vm_scripts_from_the_pinned_manifest():
    import vm_scripts
    ids = {e.entry_id for e in ic.catalog()}
    for script in vm_scripts.list_scripts():
        assert script.script_id in ids


def test_catalog_includes_both_cpu_microcode_vendors_and_both_wifi_vendors():
    ids = {e.entry_id for e in ic.catalog()}
    assert {"amd64-microcode", "intel-microcode",
            "firmware-mediatek", "firmware-realtek"} <= ids


def test_cache_path_is_grouped_by_kind():
    by_id = {e.entry_id: e for e in ic.catalog()}
    assert by_id["proxmox-ve-source"].cache_path == "isos/proxmox-ve-source.iso"
    assert by_id["ethtool"].cache_path == "packages/ethtool.deb"


# -- Mount status ------------------------------------------------------

def test_mount_status_reports_a_real_mount():
    mounted, detail = ic.mount_status(_runner(mounted=True))
    assert mounted is True
    assert "/dev/sdd2" in detail


def test_mount_status_flags_a_plain_directory_as_not_mounted():
    """The real observed failure: /mnt/INSTALLER_CACHE existing as a
    directory on the root filesystem, so artifacts silently land on the
    root disk and are lost on rebuild."""
    mounted, detail = ic.mount_status(_runner(mounted=False))
    assert mounted is False
    assert "NOT a mount point" in detail


# -- Scan and reconcile ------------------------------------------------

def test_scan_cache_reads_real_files_and_skips_directories():
    found = ic.scan_cache(_runner())
    names = [n for n, _ in found["isos"]]
    assert "proxmox-ve-source.iso" in names
    assert "nested-dir" not in names


def test_reconcile_marks_a_present_artifact_with_its_real_size():
    report = ic.reconcile(_runner())
    row = next(r for r in report.rows if r.entry.entry_id == "proxmox-ve-source")
    assert row.present is True
    assert row.size_bytes == 1706178560


def test_reconcile_matches_a_versioned_deb_by_package_stem():
    """A real .deb carries version and arch, so exact-name matching
    would report every cached package as missing."""
    report = ic.reconcile(_runner())
    row = next(r for r in report.rows if r.entry.entry_id == "ethtool")
    assert row.present is True
    assert row.actual_path == "packages/ethtool_6.10-1_amd64.deb"


def test_reconcile_lists_a_missing_artifact_rather_than_omitting_it():
    report = ic.reconcile(_runner())
    row = next(r for r in report.rows if r.entry.entry_id == "smartmontools")
    assert row.present is False
    assert "not on the volume" in row.detail


def test_every_catalog_entry_appears_in_the_report_exactly_once():
    report = ic.reconcile(_runner())
    assert len(report.rows) == len(ic.catalog())
    assert report.present_count + report.missing_count == len(report.rows)


def test_reconcile_surfaces_an_uncatalogued_file_instead_of_hiding_it():
    """An unexplained 6 GB ISO is exactly what an operator must see
    before trusting a self-replicating build."""
    report = ic.reconcile(_runner())
    extras = {e.path for e in report.extras}
    assert "isos/omarchy-4.0.4.iso" in extras


def test_extras_are_ordered_largest_first():
    report = ic.reconcile(_runner())
    sizes = [e.size_bytes for e in report.extras]
    assert sizes == sorted(sizes, reverse=True)


def test_reconcile_on_an_empty_volume_reports_everything_missing_not_an_error():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["findmnt"], FakeProc(0, "/dev/sdd2 ext4\n")),
        (lambda a: a[:1] == ["ls"], FakeProc(2, "", "No such file or directory")),
    ])
    report = ic.reconcile(runner)
    assert report.present_count == 0
    assert report.missing_count == len(ic.catalog())
    assert report.extras == []


def test_human_size_is_readable():
    assert ic.human_size(0) == "-"
    assert ic.human_size(1706178560).endswith("GiB")


# -- Container images (Project Hummingbird caddy) ----------------------

def _caddy():
    return next(e for e in ic.catalog() if e.entry_id == "caddy")


def test_caddy_is_catalogued_as_a_container_image():
    """The gateway had a Caddyfile renderer and routes but no binary in
    any acquisition path - this entry is what closes that gap."""
    assert _caddy().kind == ic.KIND_IMAGE


def test_an_image_is_referenced_by_digest_never_by_tag():
    ref = _caddy().pinned_ref
    assert ref.startswith("quay.io/hummingbird/caddy@sha256:")
    assert ":latest" not in ref and ":2.11" not in ref


def test_pinned_ref_is_empty_rather_than_a_tag_when_nothing_is_pinned():
    entry = ic.CatalogEntry("x", "x", ic.KIND_IMAGE, origin="o", install_helper="h",
                            config_section="c", registry_ref="quay.io/x/y")
    assert entry.pinned_ref == ""
    assert entry.provenance == ic.PROVENANCE_NONE


def test_an_observed_digest_is_not_reported_as_verified():
    """A digest read from a registry proves which bytes are meant, not
    that a trusted party signed them. The two states stay distinct."""
    assert _caddy().signature_verified is False
    assert _caddy().provenance == ic.PROVENANCE_OBSERVED
    assert "not yet verified" in _caddy().provenance


def test_a_verified_signature_is_its_own_state():
    entry = ic.CatalogEntry("x", "x", ic.KIND_IMAGE, origin="o", install_helper="h",
                            config_section="c", registry_ref="r", digest="sha256:ab",
                            signature_verified=True)
    assert entry.provenance == ic.PROVENANCE_VERIFIED


def test_caddy_records_when_its_digest_was_pinned_so_zero_cve_can_age():
    """'Zero-CVE' describes an image at build time. Without a date the
    catalog would present it as a standing property."""
    assert _caddy().observed_at == "2026-09-30"
    assert "not a standing property" in _caddy().notes


def test_caddy_records_its_published_supply_chain_attachments():
    attachments = " ".join(_caddy().attachments)
    for kind in (".sig", ".sbom", ".att"):
        assert kind in attachments


def test_caddy_notes_record_the_admin_port_that_must_not_be_published():
    assert "2019" in _caddy().notes


def test_images_are_cached_in_their_own_subdirectory():
    assert _caddy().cache_path == "images/caddy-2.11.4.oci.tar"
