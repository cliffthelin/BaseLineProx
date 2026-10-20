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


def test_every_secret_is_granted_to_every_machine_and_kasm(tmp_path):
    grants = tmp_path / "g.json"
    tk.run(Host(), "cliff", ENTRIES, {"debian"}, "/bases", vault_names=["GOOGLE_LOGIN", "CLAUDE_CODE_OAUTH_TOKEN"], grants_path=grants,
           create=make([]), plan_for=plan, install_base=lambda *a: None, owner_for=lambda h, u: u)
    assert vg.granted(grants, "vm:debian") == ["CLAUDE_CODE_OAUTH_TOKEN", "GOOGLE_LOGIN"]
    assert vg.granted(grants, "kasm") == ["CLAUDE_CODE_OAUTH_TOKEN", "GOOGLE_LOGIN"]


def test_running_it_again_changes_nothing(tmp_path):
    grants = tmp_path / "g.json"
    args = dict(vault_names=["GOOGLE_LOGIN"], grants_path=grants, create=make([]), plan_for=plan, install_base=lambda *a: None, owner_for=lambda h, u: u)
    host = Host()
    tk.run(host, "cliff", ENTRIES, {"debian"}, "/bases", **args)
    before = grants.stat().st_mtime_ns
    second = tk.run(host, "cliff", ENTRIES, {"debian"}, "/bases", **args)
    assert second["created"] == [] and grants.stat().st_mtime_ns == before
