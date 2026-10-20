"""Baseline serves its Kasm workspace registry: two static files, GET only, no login, from one folder; everything else still needs a session."""
import http.client
import json

import pytest

from test_baseline_web import _RealServerCase, _base_deps

LIST = {"name": "Baseline", "list_url": "http://baseline.invalid/kasm-registry/", "workspacecount": 1, "workspaces": [{"friendly_name": "Browser"}], "channels": [], "default_channel": ""}


def get(case, path, host=None, method="GET", cookie=False):
    conn = http.client.HTTPConnection("127.0.0.1", case.port, timeout=10)
    headers = {"Host": host} if host else {}
    if cookie:
        headers["Cookie"] = f"session={case.token}"
    conn.request(method, path, headers=headers)
    r = conn.getresponse()
    out = (r.status, r.getheader("Content-Type"), r.getheader("Cache-Control"), r.read().decode())
    conn.close()
    return out


@pytest.fixture
def registry(tmp_path):
    root = tmp_path / "registry"
    (root / "1.1").mkdir(parents=True)
    (root / "versions.txt").write_text("1.1\n")
    (root / "1.1" / "list.json").write_text(json.dumps(LIST))
    case = _RealServerCase(_base_deps(kasm_registry_dir=str(root)))
    case.root = root
    yield case
    case.close()


def test_the_two_registry_files_are_served_without_a_login_and_not_cached(registry):
    status, kind, cache, body = get(registry, "/kasm-registry/versions.txt")
    assert (status, kind.split(";")[0], cache, body) == (200, "text/plain", "no-store", "1.1\n")
    status, kind, _, body = get(registry, "/kasm-registry/1.1/list.json")
    assert status == 200 and kind == "application/json" and json.loads(body)["workspaces"] == [{"friendly_name": "Browser"}]


def test_the_list_names_the_address_the_client_used_not_the_one_written_at_build_time(registry):
    _, _, _, body = get(registry, "/kasm-registry/1.1/list.json", host="192.168.50.7:8100")
    assert json.loads(body)["list_url"] == "http://192.168.50.7:8100/kasm-registry/"
    _, _, _, body = get(registry, "/kasm-registry/1.1/list.json", host="bad host/<script>")
    assert json.loads(body)["list_url"] == "http://baseline.invalid/kasm-registry/"                # a Host header that is not an address is ignored, never echoed


def test_nothing_else_under_the_prefix_is_served_and_the_rest_still_needs_a_login(registry):
    (registry.root / "secret.txt").write_text("private")
    for path in ("/kasm-registry/secret.txt", "/kasm-registry/", "/kasm-registry/../secret.txt", "/kasm-registry/1.1/", "/kasm-registry/1.0/list.json"):
        status = get(registry, path)[0]
        assert status in (303, 401, 404), path                                                    # a login redirect or not found, never the file
        assert "private" not in get(registry, path)[3]
    assert get(registry, "/home")[0] == 303 and get(registry, "/vms")[0] == 303                    # the exception did not open anything else


def test_only_get_is_served(registry):
    assert get(registry, "/kasm-registry/versions.txt", method="POST")[0] != 200
    assert get(registry, "/kasm-registry/1.1/list.json", method="PUT")[0] != 200


def test_a_missing_link_or_broken_file_is_a_plain_not_found(registry, tmp_path):
    (registry.root / "1.1" / "list.json").write_text("not json")
    assert get(registry, "/kasm-registry/1.1/list.json")[0] == 404
    (registry.root / "versions.txt").unlink()
    (registry.root / "versions.txt").symlink_to(tmp_path / "registry" / "1.1" / "list.json")
    assert get(registry, "/kasm-registry/versions.txt")[0] == 404                                  # a link is never followed
    empty = _RealServerCase(_base_deps(kasm_registry_dir=str(tmp_path / "nowhere")))
    try:
        assert get(empty, "/kasm-registry/versions.txt")[0] == 404                                 # no registry carried: not found
    finally:
        empty.close()


PNG = b"\x89PNG\r\n\x1a\n" + b"icon"


def test_a_registry_icon_is_served_by_its_exact_name_without_a_login(registry, tmp_path):
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "chrome.png").write_bytes(PNG)
    (icons / "secret.txt").write_text("private")
    registry.server.deps["kasm_registry_icons_dir"] = str(icons)
    conn = http.client.HTTPConnection("127.0.0.1", registry.port, timeout=10)
    conn.request("GET", "/kasm-registry/1.1/icons/chrome.png")
    r = conn.getresponse()
    assert (r.status, r.getheader("Content-Type"), r.read()) == (200, "image/png", PNG)
    for path in ("/kasm-registry/1.1/icons/secret.txt", "/kasm-registry/1.1/icons/../secret.txt", "/kasm-registry/1.1/icons/missing.png", "/kasm-registry/1.1/icons/", "/kasm-registry/1.1/icons/Chrome.png"):
        assert get(registry, path)[0] in (303, 401, 404) and "private" not in get(registry, path)[3], path


def test_an_icon_that_is_a_link_is_never_followed(registry, tmp_path):
    icons = tmp_path / "icons2"
    icons.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    (icons / "link.png").symlink_to(outside)
    registry.server.deps["kasm_registry_icons_dir"] = str(icons)
    assert get(registry, "/kasm-registry/1.1/icons/link.png")[0] == 404
