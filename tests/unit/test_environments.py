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
