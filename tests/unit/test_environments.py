"""The environments catalogue (DR258): every carried OS image against the five guest applications, honestly marked native, helper or
not built. Names come from the real carried images; compatibility from application_bundle's own supported targets."""
import environments as env

ISOS = ["ubuntu-26.04.1-desktop-amd64.iso", "MX-25.3_Xfce_x64.iso", "cachyos-desktop-linux-260809.iso",
        "nixos-graphical-26.05.10769.cf5e76507c6e-x86_64-linux.iso", "omarchy-4.0.4.iso", "jrescue-2026.08.03-amd64.iso",
        "debian-13.1.0-amd64-netinst.iso", "ubuntu-24.04.5-live-server-amd64.iso"]


def test_each_carried_image_is_classified_by_family_and_release():
    got = {e["iso"]: (e["os"], e["release"]) for e in env.catalogue(ISOS, [])}
    assert got["ubuntu-26.04.1-desktop-amd64.iso"] == ("ubuntu", "26.04")
    assert got["ubuntu-24.04.5-live-server-amd64.iso"] == ("ubuntu", "24.04")
    assert got["debian-13.1.0-amd64-netinst.iso"] == ("debian", "13")
    assert got["cachyos-desktop-linux-260809.iso"][0] == "arch"
    assert got["nixos-graphical-26.05.10769.cf5e76507c6e-x86_64-linux.iso"][0] == "nixos"
    assert got["jrescue-2026.08.03-amd64.iso"][0] == "rescue"


def test_the_five_applications_are_native_only_where_the_bundle_supports_the_platform_and_a_helper_elsewhere():
    rows = {e["iso"]: e for e in env.catalogue(ISOS, [])}
    ubuntu = rows["ubuntu-26.04.1-desktop-amd64.iso"]
    assert set(ubuntu["apps"]) == {"vscode", "spotify", "chrome", "chatgpt", "claude"}
    assert set(ubuntu["apps"].values()) == {"native"}
    assert set(rows["cachyos-desktop-linux-260809.iso"]["apps"].values()) == {"helper"}
    assert set(rows["jrescue-2026.08.03-amd64.iso"]["apps"].values()) == {"none"}          # a rescue image runs nothing of ours


def test_an_environment_counts_as_built_only_when_a_vm_or_container_of_that_name_exists():
    rows = env.catalogue(["ubuntu-26.04.1-desktop-amd64.iso"], [{"name": "ubuntu-26.04", "type": "qemu", "status": "stopped"}])
    assert rows[0]["state"] == "built" and rows[0]["vm"] == "ubuntu-26.04"
    assert env.catalogue(["ubuntu-26.04.1-desktop-amd64.iso"], [])[0]["state"] == "not built"


def test_the_page_lists_every_row_and_never_claims_apps_are_installed():
    html = env.render(env.catalogue(ISOS, [])).decode()
    for iso in ISOS:
        assert iso in html
    assert "not built" in html and "installed" not in html.lower().replace("not installed", "")


def test_qubes_fydeos_and_bazzite_are_recognised_and_marked_helper_not_native():
    rows = {e["iso"]: e for e in env.catalogue(["Qubes-R4.3.2-x86_64.iso", "FydeOS-VMWare-v23.0-Preview2-x86_64-io.ova", "bazzite-stable-amd64.iso", "omarchy-4.0.4.iso"], [])}
    assert (rows["Qubes-R4.3.2-x86_64.iso"]["os"], rows["FydeOS-VMWare-v23.0-Preview2-x86_64-io.ova"]["os"], rows["bazzite-stable-amd64.iso"]["os"]) == ("qubes", "chromeos", "fedora")
    assert rows["omarchy-4.0.4.iso"]["os"] == "arch"
    assert all(set(r["apps"].values()) == {"helper"} for r in rows.values())


LISTING = [
    {"id": "debian", "name": "Debian 13", "kind": "vm", "iso": "debian-13.7.0-amd64-DVD-1.iso", "apps": ["vscode", "chrome"], "notes": ""},
    {"id": "qubes", "name": "Qubes OS 4.3", "kind": "vm", "iso": "Qubes-R4.3.2-x86_64.iso", "apps": list(env.APPS), "notes": ""},
    {"id": "bazzite", "name": "Bazzite", "kind": "vm", "iso": "bazzite-stable-amd64.iso", "apps": [], "notes": ""},
    {"id": "kasm-workspaces", "name": "Kasm", "kind": "kasm", "iso": None, "apps": [], "notes": ""},
]


def test_the_listed_catalogue_follows_the_list_not_the_images_on_the_drive():
    rows = env.listed_catalogue(LISTING, ["debian-13.7.0-amd64-DVD-1.iso", "Qubes-R4.3.2-x86_64.iso", "something-else.iso"], [])
    assert [r["id"] for r in rows] == ["debian", "qubes", "bazzite"]                      # in the list's order; Kasm is not a guest OS; the stray image is not shown
    assert rows[0]["apps"] == {"vscode": "native", "spotify": "not planned", "chrome": "native", "chatgpt": "not planned", "claude": "not planned"}
    assert set(rows[1]["apps"].values()) == {"helper"} and set(rows[2]["apps"].values()) == {"not planned"}


def test_an_image_the_list_names_but_the_drive_lacks_is_marked_missing_not_hidden():
    rows = env.listed_catalogue(LISTING, ["debian-13.7.0-amd64-DVD-1.iso"], [])
    assert [r["image"] for r in rows] == ["carried", "missing", "missing"]
    page = env.render(rows).decode()
    assert "image missing" in page and "not planned" in page and "Debian 13" in page


def test_a_listed_os_is_built_when_a_vm_of_that_id_or_family_exists():
    rows = env.listed_catalogue(LISTING, [], [{"name": "debian-13-dev"}])
    assert rows[0]["state"] == "built" and rows[0]["vm"] == "debian-13-dev" and rows[1]["state"] == "not built"


def test_the_lists_file_names_match_proxmox_volume_names_and_the_hosts_own_name_is_kept():
    """Found on a real Proxmox (2026-10-17): it names images `installer-cache:iso/<file>`; matching whole names marked every listed image missing."""
    listing = [{"id": "debian", "name": "Debian 13", "kind": "vm", "iso": "debian-13.7.0-amd64-DVD-1.iso", "apps": [], "notes": ""}]
    carried = ["baseline-os:iso/debian-installer.iso", "installer-cache:iso/debian-13.7.0-amd64-DVD-1.iso"]
    row = env.listed_catalogue(listing, carried, [])[0]
    assert row["image"] == "carried" and row["carried_as"] == "installer-cache:iso/debian-13.7.0-amd64-DVD-1.iso"
    assert env.listed_catalogue(listing, ["debian-13.7.0-amd64-DVD-1.iso"], [])[0]["carried_as"] == "debian-13.7.0-amd64-DVD-1.iso"      # a local folder: plain names
    assert env.listed_catalogue(listing, ["installer-cache:iso/other.iso"], [])[0]["image"] == "missing"
    assert env.match_image("a.iso", ["x:iso/xa.iso"]) is None                                   # the whole file name, never a suffix of it


def test_a_carried_ready_made_base_is_shown_beside_the_image_state():
    rows = env.listed_catalogue(LISTING, [], [], bases={"debian"})
    by_id = {r["id"]: r for r in rows}
    assert by_id["debian"]["base"] is True and by_id["qubes"]["base"] is False
    assert "ready-made base carried" in env.render(rows).decode()
