"""Turnkey setup for the signed-in user: a machine for every ready-made system the build carries (owner account made, the agreed applications preset), and every vault secret granted to every
machine and to Kasm, so nothing is left for the person to set up."""
import turnkey as tk
import vault_grants as vg


ENTRIES = [{"id": "debian", "name": "Debian", "kind": "vm", "apps": ["vscode", "chrome"]},
           {"id": "ubuntu", "name": "Ubuntu", "kind": "vm", "apps": ["vscode"]},
           {"id": "kasm", "name": "Kasm", "kind": "kasm", "apps": []},
           {"id": "qubes", "name": "Qubes", "kind": "vm", "apps": []}]


class Host:
    def __init__(self, existing=()):
        self.vms = [{"name": n} for n in existing]

    def list_vms(self):
        return self.vms


def make(created, existing=(), fail=None):
    def create(host, name, os_id, *, owner, extra):
        if fail == os_id:
            raise RuntimeError("boom")
        created.append((name, os_id, owner, extra))
        host.vms.append({"name": name})
        return {"name": name}
    return create


def plan(app, os_id):
    if app == "chrome" and os_id == "debian":
        raise tk.AppEnvError("no route")
    return {"app": app, "name": app, "os": os_id, "script": f"install {app}", "launch": app, "mounts": [], "headless": False}


def test_a_machine_is_made_for_each_carried_system_with_the_owner_and_applications(tmp_path):
    created = []
    report = tk.run(Host(), "cliff", ENTRIES, {"debian", "ubuntu"}, "/bases", vault_names=[], grants_path=tmp_path / "g.json",
                    create=make(created), plan_for=plan, install_base=lambda *a: None, owner_for=lambda host, user: user)
    assert [c[:3] for c in created] == [("debian", "debian", "cliff"), ("ubuntu", "ubuntu", "cliff")]
    paths = {f["path"] for f in created[0][3]["write_files"]}
    assert "/var/lib/baseline/install-app-vscode.sh" in paths and "/var/lib/baseline/install-app-chrome.sh" not in paths
    assert report["created"] == ["debian", "ubuntu"] and "chrome" in report["apps_skipped"]["debian"]
    assert report["not_carried"] == []


def test_existing_machines_are_left_alone(tmp_path):
    created = []
    report = tk.run(Host(["debian"]), "cliff", ENTRIES, {"debian"}, "/bases", vault_names=[], grants_path=tmp_path / "g.json",
                    create=make(created), plan_for=plan, install_base=lambda *a: None, owner_for=lambda h, u: u)
    assert created == [] and report["already_there"] == ["debian"]


def test_one_failing_system_does_not_stop_the_others(tmp_path):
    created = []
    report = tk.run(Host(), "cliff", ENTRIES, {"debian", "ubuntu"}, "/bases", vault_names=[], grants_path=tmp_path / "g.json",
                    create=make(created, fail="debian"), plan_for=plan, install_base=lambda *a: None, owner_for=lambda h, u: u)
    assert report["created"] == ["ubuntu"] and "debian" in report["failed"]


def test_turnkey_never_grants_vault_secrets_automatically(tmp_path):
    grants = tmp_path / "g.json"
    tk.run(Host(), "cliff", ENTRIES, {"debian"}, "/bases", vault_names=["GOOGLE_LOGIN", "CLAUDE_CODE_OAUTH_TOKEN"], grants_path=grants,
           create=make([]), plan_for=plan, install_base=lambda *a: None, owner_for=lambda h, u: u)
    assert vg.granted(grants, "vm:debian") == []
    assert vg.granted(grants, "kasm") == []


def test_running_it_again_changes_nothing(tmp_path):
    grants = tmp_path / "g.json"
    args = dict(vault_names=["GOOGLE_LOGIN"], grants_path=grants, create=make([]), plan_for=plan, install_base=lambda *a: None, owner_for=lambda h, u: u)
    host = Host()
    tk.run(host, "cliff", ENTRIES, {"debian"}, "/bases", **args)
    second = tk.run(host, "cliff", ENTRIES, {"debian"}, "/bases", **args)
    assert second["created"] == [] and not grants.exists()


def test_the_five_default_applications_are_all_in_the_catalogue_and_chrome_resolves_on_debian():
    import app_catalogue as ac
    import os_list
    catalogue = ac.load()
    assert set(os_list.APPS) <= set(catalogue)
    found = {"url": "https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_1_amd64.deb", "sha256": "a" * 64}
    plan_ = tk.resolved_plan("chrome", "debian", resolve=lambda entry, os_id: found)
    assert plan_["route"] == "deb" and "google-chrome-stable" in plan_["script"] and "a" * 64 in plan_["script"]


def test_a_package_that_cannot_be_found_is_reported_not_installed_unchecked():
    import app_catalogue as ac
    def resolve(entry, os_id):
        raise ac.CatalogueError("could not read the index")
    try:
        tk.resolved_plan("claude", "debian", resolve=resolve)
    except tk.AppEnvError as exc:
        assert "could not be found" in str(exc)
    else:
        raise AssertionError("expected a refusal")


def test_without_a_name_for_the_person_no_machine_is_made_and_the_person_is_asked(tmp_path):
    import prebuilt_environment as pe
    created = []
    def owner_for(host, user):
        raise pe.OwnerUnknown("unknown")
    report = tk.run(Host(), "root@pam", ENTRIES, {"debian"}, "/bases", vault_names=["GOOGLE_LOGIN"], grants_path=tmp_path / "g.json",
                    create=make(created), plan_for=plan, install_base=lambda *a: None, owner_for=owner_for)
    assert created == [] and report["needs_owner"] is True and report["created"] == []


def test_applications_already_in_the_carried_base_are_not_downloaded_again(tmp_path):
    created = []
    report = tk.run(Host(), "cliff", ENTRIES, {"debian", "ubuntu"}, "/bases", vault_names=[], grants_path=tmp_path / "g.json", create=make(created), plan_for=plan,
                    install_base=lambda *a: None, owner_for=lambda h, u: u, installed_in=lambda d, os_id: {"vscode", "chrome"} if os_id == "debian" else set())
    debian = created[0][3]
    assert "/var/lib/baseline/install-app-vscode.sh" not in {f["path"] for f in debian["write_files"]}
    assert "/usr/local/bin/google-chrome-stable" in {f["path"] for f in debian["write_files"]}        # started with the shared password store
    assert report["apps_preinstalled"]["debian"] == ["vscode", "chrome"]
    assert "/var/lib/baseline/install-app-vscode.sh" in {f["path"] for f in created[1][3]["write_files"]}


def test_the_manifest_of_a_base_names_what_it_carries():
    manifest = {"holds_install_state_or_secrets": False, "apps": {"vscode": "1", "google-chrome": "nixpkgs", "spotify": "x"}}
    assert tk.preinstalled("/b", "nixos", read_manifest=lambda d, o: manifest) == {"vscode", "chrome", "spotify"}
    assert tk.preinstalled("/b", "cachyos", read_manifest=lambda d, o: {"holds_install_state_or_secrets": False}) == set()
