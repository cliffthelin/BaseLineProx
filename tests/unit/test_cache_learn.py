"""The drive's own cache learns what it had to fetch, so the next rebuild depends less on outside resources.

Real .deb files built with dpkg-deb, real directories; the integrity check is the same one first boot uses."""
import gzip
import json
import subprocess

import pytest

import cache_learn
import offline_cache


def _deb(folder, name, version="1.0", arch="amd64"):
    root = folder / f"build-{name}-{version}"
    (root / "DEBIAN").mkdir(parents=True)
    (root / "DEBIAN/control").write_text(
        f"Package: {name}\nVersion: {version}\nArchitecture: {arch}\nMaintainer: t <t@example.invalid>\n"
        f"Description: test package {name}\n")
    (root / "usr/share").mkdir(parents=True)
    (root / f"usr/share/{name}").write_text(name * 50)
    out = folder / f"{name}_{version}_{arch}.deb"
    subprocess.run(["dpkg-deb", "--build", str(root), str(out)], check=True, capture_output=True)
    return out


def _carried_cache(tmp_path):
    cache = tmp_path / "cache"
    (cache / "apt").mkdir(parents=True)
    base = _deb(tmp_path, "basepkg")
    (cache / "apt" / base.name).write_bytes(base.read_bytes())
    (cache / "apt/Packages").write_text(cache_learn.stanza(cache / "apt" / base.name))
    (cache / "apt/Packages.gz").write_bytes(gzip.compress((cache / "apt/Packages").read_bytes()))
    (cache / "MANIFEST.json").write_text(json.dumps(offline_cache.build_manifest(cache)))
    return cache


def test_a_downloaded_package_is_added_to_the_carried_repository_and_its_index(tmp_path):
    cache = _carried_cache(tmp_path)
    archives = tmp_path / "archives"
    archives.mkdir()
    new = _deb(archives, "newpkg", "2.1")
    report = cache_learn.harvest(archives, cache, source="apt install newpkg (online)")
    assert [r["file"] for r in report["learned"]] == [new.name]
    assert (cache / "apt" / new.name).read_bytes() == new.read_bytes()
    index = gzip.decompress((cache / "apt/Packages.gz").read_bytes()).decode()
    assert "Package: newpkg" in index and "Package: basepkg" in index
    assert f"Filename: ./{new.name}" in index and index == (cache / "apt/Packages").read_text()


def test_learned_files_do_not_break_the_integrity_check_but_tampering_still_does(tmp_path):
    cache = _carried_cache(tmp_path)
    archives = tmp_path / "archives"
    archives.mkdir()
    new = _deb(archives, "newpkg")
    manifest = json.loads((cache / "MANIFEST.json").read_text())
    cache_learn.harvest(archives, cache, source="test")
    with pytest.raises(RuntimeError):                         # the immutable base alone no longer matches ...
        offline_cache.verify_manifest(cache, manifest)
    assert offline_cache.verify_carried(cache) > len(manifest)  # ... the base plus what was learned does
    (cache / "apt" / new.name).write_bytes(b"corrupted")
    with pytest.raises(RuntimeError):
        offline_cache.verify_carried(cache)


def test_an_unrecorded_extra_file_is_still_refused(tmp_path):
    cache = _carried_cache(tmp_path)
    (cache / "apt/stray.deb").write_bytes(b"not recorded anywhere")
    with pytest.raises(RuntimeError):
        offline_cache.verify_carried(cache)


def test_what_the_cache_already_carries_is_not_added_again_and_a_bad_file_is_never_added(tmp_path):
    cache = _carried_cache(tmp_path)
    archives = tmp_path / "archives"
    archives.mkdir()
    (archives / "basepkg_1.0_amd64.deb").write_bytes((cache / "apt/basepkg_1.0_amd64.deb").read_bytes())
    (archives / "broken_1.0_amd64.deb").write_bytes(b"this is not a package")
    wrong_arch = _deb(archives, "armpkg", arch="arm64")
    report = cache_learn.harvest(archives, cache, source="test")
    assert report["learned"] == []
    assert {s["file"] for s in report["skipped"]} == {"broken_1.0_amd64.deb", wrong_arch.name}
    assert offline_cache.verify_carried(cache) == len(json.loads((cache / "MANIFEST.json").read_text()))


def test_the_record_says_where_each_addition_came_from(tmp_path):
    cache = _carried_cache(tmp_path)
    archives = tmp_path / "archives"
    archives.mkdir()
    _deb(archives, "newpkg")
    cache_learn.harvest(archives, cache, source="apt install newpkg (online)")
    record = json.loads((cache / "LEARNED.json").read_text())
    assert record["log"][0]["package"] == "newpkg" and record["log"][0]["source"] == "apt install newpkg (online)"
    assert "apt/Packages" in record["files"] and "apt/Packages.gz" in record["files"]


def test_an_application_the_drive_had_to_download_is_kept_for_the_next_rebuild(tmp_path):
    import hashlib
    cache = _carried_cache(tmp_path)
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    data = b"a newer build of the app"
    (prepared / "source.deb").write_bytes(data)
    (prepared / "recipe.json").write_text(json.dumps({
        "app": "chrome", "configuration": {}, "format": "baseline.application-build/v1",
        "platform": {"arch": "amd64", "os": "debian", "release": "13"},
        "source": {"medium": "deb", "package": "google-chrome-stable", "sha256": hashlib.sha256(data).hexdigest(),
                   "url": "https://example.invalid/c.deb", "version": "9.9"}}))
    cache_learn.learn_app(cache, "chrome", prepared, source="baseline-apps prepare (online)")
    assert offline_cache.verify_app_bundle(cache, ("chrome",))[0]["version"] == "9.9"
    assert offline_cache.verify_carried(cache) > 0
    (prepared / "source.deb").write_bytes(b"does not match the recipe")
    with pytest.raises(RuntimeError):
        cache_learn.learn_app(cache, "chrome2", prepared, source="x")


def test_the_apt_hook_is_provisioned_and_never_fails_a_package_operation():
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    provision = (repo / "boot/provision.sh").read_text()
    for name in ("baseline/lib/cache_learn.py", "baseline/bin/baseline-cache-learn", "99baseline-cache-learn"):
        assert name in provision, name
    conf = (repo / "boot/baseline-cache-learn.apt.conf").read_text()
    assert "DPkg::Post-Invoke" in conf and conf.strip().endswith('|| true"; };')
    assert (repo / "baseline/bin/baseline-cache-learn").stat().st_mode & 0o111


def test_the_hook_does_nothing_on_a_system_without_an_installer_cache(tmp_path):
    from pathlib import Path
    import subprocess
    import sys
    repo = Path(__file__).resolve().parents[2]
    proc = subprocess.run([sys.executable, str(repo / "baseline/bin/baseline-cache-learn")], capture_output=True, text=True)
    assert proc.returncode == 0 and proc.stdout == ""
