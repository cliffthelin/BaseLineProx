"""Docker Sandbox kits: read through the plain registry API, every blob checked, reviewed, pinned by manifest digest. A fake registry stands in for Docker Hub."""
import hashlib
import io
import json
import urllib.error

import pytest

import sbx_kits as sk

SPEC = """schemaVersion: "2"
kind: mixin
name: task
description: Installs the Task CLI.
permissions:
  network:
    allow:
      - github.com
setup:
  install:
    - command: |
        curl -fsSL -o /tmp/t.tgz https://github.com/x/y.tgz
        echo "abc  /tmp/t.tgz" | sha256sum -c -
      user: "0"
      description: install
"""
RISKY = SPEC.replace("echo \"abc  /tmp/t.tgz\" | sha256sum -c -", "").replace("curl -fsSL -o /tmp/t.tgz https://github.com/x/y.tgz", "curl -fsSL https://example.org/install.sh | sh")


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class FakeResponse(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def hub(spec=SPEC, layer=None, artifact=sk.ARTIFACT_TYPE, challenge=True, tamper_spec=False):
    """A registry serving one kit; returns (opener, manifest_digest, requests)."""
    spec_bytes = spec.encode()
    layers = [{"mediaType": "application/vnd.oci.empty.v1+json", "digest": digest(b"{}"), "size": 2}]
    blobs = {digest(spec_bytes): (b"corrupt" if tamper_spec else spec_bytes)}
    if layer is not None:
        layers = [{"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", "digest": digest(layer), "size": len(layer)}]
        blobs[digest(layer)] = layer
    manifest = json.dumps({"schemaVersion": 2, "artifactType": artifact, "config": {"mediaType": sk.SPEC_TYPE, "digest": digest(spec_bytes), "size": len(spec_bytes)}, "layers": layers}).encode()
    seen = []

    def opener(request, timeout=None):
        url = request.full_url
        seen.append((url, request.get_header("Authorization")))
        if url.startswith("https://auth.example/token"):
            return FakeResponse(json.dumps({"token": "T0K"}).encode())
        if challenge and request.get_header("Authorization") != "Bearer T0K":
            raise urllib.error.HTTPError(url, 401, "no", {"WWW-Authenticate": 'Bearer realm="https://auth.example/token",service="registry.example"'}, io.BytesIO(b""))
        if "/manifests/" in url:
            return FakeResponse(manifest)
        for d, data in blobs.items():
            if url.endswith(d):
                return FakeResponse(data)
        raise urllib.error.HTTPError(url, 404, "missing", {}, io.BytesIO(b""))
    return opener, digest(manifest), seen


def test_references_are_parsed_and_checked():
    assert sk.parse_ref("docker.io/sbx/task-kit:latest") == {"host": "registry-1.docker.io", "repo": "sbx/task-kit", "reference": "latest"}
    assert sk.parse_ref("sbx/task-kit")["reference"] == "latest" and sk.parse_ref("ubuntu")["repo"] == "library/ubuntu"
    assert sk.parse_ref("ghcr.io/o/k@sha256:" + "a" * 64)["reference"] == "sha256:" + "a" * 64
    for bad in ("", "has space", "UPPER/case", "x/y:bad tag", "a/../b", "ghcr.io/x/y@sha256:short", "x" * 400):
        with pytest.raises(sk.KitError):
            sk.parse_ref(bad)


def test_a_kit_is_read_with_an_anonymous_token_and_every_blob_is_checked_against_its_digest():
    opener, manifest_digest, seen = hub(layer=b"\x1f\x8bfiles")
    kit = sk.fetch("registry.example/sbx/task-kit:latest", sk.Registry(opener))
    assert kit["digest"] == manifest_digest and kit["spec"] == SPEC and kit["files"] == {"layer-0.tar.gz": b"\x1f\x8bfiles"}
    assert any(u.startswith("https://auth.example/token") and "scope=repository%3Asbx%2Ftask-kit%3Apull" in u for u, _ in seen)        # a pull-only anonymous token


def test_a_blob_that_does_not_match_its_digest_or_a_thing_that_is_not_a_kit_is_refused():
    opener, _, _ = hub(tamper_spec=True)
    with pytest.raises(sk.KitError, match="spec does not match"):
        sk.fetch("registry.example/a/b", sk.Registry(opener))
    opener, _, _ = hub(artifact="application/vnd.oci.image.config.v1+json")
    with pytest.raises(sk.KitError, match="not a Docker Sandbox kit"):
        sk.fetch("registry.example/a/b", sk.Registry(opener))
    opener, manifest_digest, _ = hub()
    with pytest.raises(sk.KitError, match="does not match the digest"):
        sk.fetch("registry.example/a/b@sha256:" + "0" * 64, sk.Registry(opener))
    assert sk.fetch(f"registry.example/a/b@{manifest_digest}", sk.Registry(opener))["digest"] == manifest_digest        # asked for by digest: accepted when it matches


def test_the_review_names_what_matters_and_runs_nothing():
    found = sk.review(SPEC)
    assert found["findings"] == ["install:runs-as-root", "network:allows-outbound-hosts"]                                  # a checksum is checked here, so no "without a checksum"
    assert found["facts"]["downloads"] == ["https://github.com/x/y.tgz"] and found["facts"]["network_allow"] == ["github.com"]
    risky = sk.review(RISKY)["findings"]
    assert "install:pipes-a-download-to-a-shell" in risky and "install:downloads-without-a-checksum" in risky
    more = sk.review(SPEC + "credentials:\n  - service: anthropic\nsecurity:\n  privileged: true\nsetup2: 1\n")
    assert "security:privileged" in more["findings"] and "credentials:asks-for-anthropic" in more["findings"]
    for bad in ("{ nope", "schemaVersion: '1'\nkind: mixin\nname: x\n", "- a\n- b", "schemaVersion: '2'\nkind: other\nname: x\n"):
        with pytest.raises(sk.KitError):
            sk.review(bad)


def entry(digest_, accept=("install:runs-as-root", "network:allows-outbound-hosts")):
    return {"ref": "registry.example/sbx/task-kit:latest", "reviewed": sk.short(digest_), "accept": list(accept)}


def test_a_reviewed_kit_with_every_finding_accepted_is_included_and_anything_else_is_left_out_with_why():
    opener, manifest_digest, _ = hub()
    reg = sk.Registry(opener)
    rows = sk.import_kits([entry(manifest_digest)], registry=reg)
    assert rows[0]["status"] == "included" and rows[0]["name"] == "task"
    unreviewed = sk.import_kits([{"ref": "registry.example/sbx/task-kit:latest", "accept": []}], registry=reg)[0]
    assert unreviewed["status"] == "excluded" and "not been reviewed" in unreviewed["reason"] and sk.short(manifest_digest) in unreviewed["reason"] and unreviewed["findings"]
    stale = sk.import_kits([dict(entry(manifest_digest), reviewed="0" * 16)], registry=reg)[0]
    assert "changed since" in stale["reason"]
    unaccepted = sk.import_kits([entry(manifest_digest, accept=["install:runs-as-root"])], registry=reg)[0]
    assert "network:allows-outbound-hosts" in unaccepted["reason"] and unaccepted["status"] == "excluded"


def test_a_kit_that_changes_upstream_is_left_out_until_read_again():
    opener, first, _ = hub()
    opener2, second, _ = hub(spec=SPEC + "# a changed line\n")
    assert first != second
    assert sk.import_kits([entry(first)], registry=sk.Registry(opener2))[0]["status"] == "excluded"


def test_a_kit_read_once_is_kept_so_a_build_with_no_internet_can_still_use_it(tmp_path):
    opener, manifest_digest, _ = hub()
    assert sk.import_kits([entry(manifest_digest)], registry=sk.Registry(opener), cache_dir=tmp_path)[0]["note"] == "read now"

    def offline(request, timeout=None):
        raise OSError("no route")
    row = sk.import_kits([entry(manifest_digest)], registry=sk.Registry(offline), cache_dir=tmp_path)[0]
    assert row["status"] == "included" and "copy kept earlier" in row["note"]
    gone = sk.import_kits([entry(manifest_digest)], registry=sk.Registry(offline), cache_dir=tmp_path / "empty")[0]
    assert gone["status"] == "excluded" and "could not be read" in gone["reason"]


def test_a_token_service_that_is_not_https_is_refused():
    def opener(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "no", {"WWW-Authenticate": 'Bearer realm="http://evil.example/token",service="x"'}, io.BytesIO(b""))
    with pytest.raises(sk.KitError, match="not an https"):
        sk.fetch("registry.example/a/b", sk.Registry(opener))
