"""Docker Sandbox kits as a reviewed, pinned, copyable catalogue (DR265, DR266 item 1).

A kit is an OCI artifact (`artifactType application/vnd.docker.sandbox.kit.v2`): its `spec.yaml` is the artifact's config blob and any `files/` tree is one small layer. A kit installs
software as root, can ask for credentials and network access, and most of them download things when a sandbox is created. So, as for registry workspaces (kasm_sources), nothing is used
because it exists: the recipe names a kit, pins it to the MANIFEST digest the person read (which covers the spec and every file), and each thing the review finds in it that matters must be
accepted by name. A kit that changed since it was read is left out, with its new digest and what it now does, until read again.

Reading a kit needs only the ordinary registry API (anonymous pulls work on Docker Hub), so this needs neither the proprietary `sbx` tool nor a Docker account. Fetching is size-limited and every
blob is checked against its digest before it is looked at. A kept copy lets a build with no internet still use a kit it has seen.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ARTIFACT_TYPE = "application/vnd.docker.sandbox.kit.v2"
SPEC_TYPE = "application/vnd.docker.sandbox.kit.v2.spec+yaml"
MANIFEST_TYPES = "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"
MAX_SPEC = 128 * 1024
MAX_LAYER = 8 * 1024 * 1024
MAX_MANIFEST = 64 * 1024
TIMEOUT_S = 30
_REPO = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*$")
_TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_HOST = re.compile(r"^[a-z0-9.-]+(:[0-9]+)?$")


class KitError(ValueError):
    pass


def parse_ref(ref: str) -> dict:
    """`docker.io/sbx/task-kit:latest`, `sbx/task-kit` or `ghcr.io/x/y@sha256:...` as {host, repo, reference}. Docker Hub's short names get `registry-1.docker.io`; everything is checked."""
    if not isinstance(ref, str) or not ref or len(ref) > 300 or re.search(r"[\s\\]", ref):
        raise KitError("a kit reference is one plain line")
    name, reference = ref, "latest"
    if "@" in ref:
        name, reference = ref.split("@", 1)
    elif ":" in ref.rsplit("/", 1)[-1]:
        name, reference = ref.rsplit(":", 1)
    parts = name.split("/")
    host = "docker.io"
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        host, parts = parts[0], parts[1:]
    repo = "/".join(parts)
    if host == "docker.io" and "/" not in repo:
        repo = "library/" + repo
    if not _HOST.match(host) or not _REPO.match(repo) or not (_DIGEST.match(reference) or _TAG.match(reference)):
        raise KitError(f"{ref!r} is not a valid kit reference")
    return {"host": "registry-1.docker.io" if host == "docker.io" else host, "repo": repo, "reference": reference}


class Registry:
    """A minimal read-only registry client: anonymous bearer tokens, size limits, nothing written."""

    def __init__(self, opener=urllib.request.urlopen, scheme="https"):
        self.opener, self.scheme, self._tokens = opener, scheme, {}

    def _open(self, url, headers, limit):
        request = urllib.request.Request(url, headers=headers)
        try:
            with self.opener(request, timeout=TIMEOUT_S) as response:
                data = response.read(limit + 1)
                return data, response.headers
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise _Challenge(exc.headers.get("WWW-Authenticate", "")) from None
            raise KitError(f"{url}: {exc.code}") from None
        except OSError as exc:
            raise KitError(f"could not reach {url}: {exc}") from None

    def get(self, host, repo, path, accept, limit):
        url = f"{self.scheme}://{host}/v2/{repo}/{path}"
        headers = {"Accept": accept, "User-Agent": "baseline-sbx-kits"}
        if (host, repo) in self._tokens:
            headers["Authorization"] = "Bearer " + self._tokens[(host, repo)]
        try:
            data, response_headers = self._open(url, headers, limit)
        except _Challenge as challenge:
            self._tokens[(host, repo)] = self._token(challenge.header, repo)
            headers["Authorization"] = "Bearer " + self._tokens[(host, repo)]
            try:
                data, response_headers = self._open(url, headers, limit)
            except _Challenge:
                raise KitError(f"{host} refused anonymous access to {repo}") from None
        if len(data) > limit:
            raise KitError(f"{url} is larger than {limit} bytes")
        return data, response_headers

    def _token(self, header: str, repo: str) -> str:
        fields = dict(re.findall(r'(\w+)="([^"]*)"', header))
        realm = fields.get("realm", "")
        if not realm.startswith("https://") and not realm.startswith(self.scheme + "://"):
            raise KitError("the registry's token service is not an https address")
        query = urllib.parse.urlencode({"service": fields.get("service", ""), "scope": f"repository:{repo}:pull"})
        try:
            data, _ = self._open(f"{realm}?{query}", {"User-Agent": "baseline-sbx-kits"}, 64 * 1024)
        except _Challenge:
            raise KitError("the registry's token service wanted credentials") from None
        try:
            document = json.loads(data.decode())
            token = document.get("token") or document.get("access_token")
        except (ValueError, AttributeError):
            token = None
        if not token:
            raise KitError("the registry gave no anonymous token")
        return token


class _Challenge(Exception):
    def __init__(self, header):
        self.header = header


def _digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def fetch(ref: str, registry=None) -> dict:
    """Read a kit: {ref, host, repo, digest (of the manifest), spec (text), files {path: bytes}}. Every blob is checked against the digest the manifest names."""
    registry = registry or Registry()
    parsed = parse_ref(ref)
    raw, headers = registry.get(parsed["host"], parsed["repo"], f"manifests/{parsed['reference']}", MANIFEST_TYPES, MAX_MANIFEST)
    digest = _digest_of(raw)
    if _DIGEST.match(parsed["reference"]) and parsed["reference"] != digest:
        raise KitError("the manifest does not match the digest it was asked for")
    try:
        manifest = json.loads(raw.decode())
    except ValueError:
        raise KitError("the manifest is not JSON") from None
    if manifest.get("artifactType") != ARTIFACT_TYPE or (manifest.get("config") or {}).get("mediaType") != SPEC_TYPE:
        raise KitError("this is not a Docker Sandbox kit (v2)")
    config = manifest["config"]
    if not _DIGEST.match(str(config.get("digest", ""))) or int(config.get("size", 0)) > MAX_SPEC:
        raise KitError("the kit's spec is missing or too large")
    spec, _ = registry.get(parsed["host"], parsed["repo"], f"blobs/{config['digest']}", "*/*", MAX_SPEC)
    if _digest_of(spec) != config["digest"]:
        raise KitError("the kit's spec does not match its digest")
    files = {}
    for index, layer in enumerate(manifest.get("layers") or []):
        if layer.get("mediaType") == "application/vnd.oci.empty.v1+json":
            continue
        if not _DIGEST.match(str(layer.get("digest", ""))) or int(layer.get("size", 0)) > MAX_LAYER:
            raise KitError("a file layer is missing a digest or too large")
        blob, _ = registry.get(parsed["host"], parsed["repo"], f"blobs/{layer['digest']}", "*/*", MAX_LAYER)
        if _digest_of(blob) != layer["digest"]:
            raise KitError("a file layer does not match its digest")
        files[f"layer-{index}.tar.gz"] = blob
    try:
        text = spec.decode()
    except UnicodeDecodeError:
        raise KitError("the kit's spec is not text") from None
    return {"ref": ref, "host": parsed["host"], "repo": parsed["repo"], "digest": digest, "spec": text, "files": files}


# ---- review --------------------------------------------------------------------------------------------------------------------------------
_URL = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")
_PIPE_TO_SHELL = re.compile(r"(curl|wget)[^|\n]*\|\s*(sudo\s+)?(sh|bash)\b")


def review(spec_text: str) -> dict:
    """What a person must read: the parsed spec, and findings named so a recipe can accept them one by one. Nothing is run. `facts` is what the kit says about itself; `findings` is what matters."""
    try:
        spec = yaml.safe_load(spec_text)
    except yaml.YAMLError:
        raise KitError("the spec is not valid YAML") from None
    if not isinstance(spec, dict) or str(spec.get("schemaVersion")) != "2" or spec.get("kind") not in ("sandbox", "mixin") or not isinstance(spec.get("name"), str):
        raise KitError("the spec is not a v2 kit (schemaVersion 2, a kind of sandbox or mixin, a name)")
    findings, facts = [], {"name": spec["name"], "kind": spec["kind"], "description": str(spec.get("description", ""))[:400]}
    install = (spec.get("setup") or {}).get("install") or []
    startup = (spec.get("setup") or {}).get("startup") or []
    commands = []
    for entry in install if isinstance(install, list) else []:
        if isinstance(entry, dict):
            command = str(entry.get("command", ""))
            user = str(entry.get("user", "0"))
            commands.append({"command": command, "user": user, "description": str(entry.get("description", ""))})
            if user in ("0", "root"):
                findings.append("install:runs-as-root")
            if _PIPE_TO_SHELL.search(command):
                findings.append("install:pipes-a-download-to-a-shell")
            if _URL.search(command) and "sha256sum" not in command and "SHA256" not in command and "--digest" not in command:
                findings.append("install:downloads-without-a-checksum")
    if startup:
        findings.append("startup:runs-commands-at-every-start")
    facts["install"], facts["downloads"] = commands, sorted({u for c in commands for u in _URL.findall(c["command"])})
    network = ((spec.get("permissions") or {}).get("network") or {})
    allow = [str(h) for h in (network.get("allow") or [])] if isinstance(network, dict) else []
    facts["network_allow"], facts["network_deny"] = allow, [str(h) for h in (network.get("deny") or [])] if isinstance(network, dict) else []
    if any("*" in h for h in allow):
        findings.append("network:wildcard-host")
    if allow:
        findings.append("network:allows-outbound-hosts")
    credentials = spec.get("credentials") or []
    facts["credentials"] = [str(c.get("service")) for c in credentials if isinstance(c, dict)]
    if facts["credentials"]:
        findings.append("credentials:asks-for-" + ",".join(sorted(facts["credentials"])))
    if (spec.get("security") or {}).get("privileged"):
        findings.append("security:privileged")
    sandbox = spec.get("sandbox") or {}
    facts["image"] = str(sandbox.get("image", "")) if isinstance(sandbox, dict) else ""
    if facts["image"] and "@sha256:" not in facts["image"]:
        findings.append("image:not-pinned-by-digest")
    facts["ports"] = [p.get("container") for p in (spec.get("ports") or []) if isinstance(p, dict)]
    facts["volumes"] = [str(v.get("path")) for v in (spec.get("volumes") or []) if isinstance(v, dict)]
    facts["requires"] = spec.get("requires") or {}
    return {"facts": facts, "findings": sorted(set(findings))}


# ---- the catalogue ---------------------------------------------------------------------------------------------------------------------------
def short(digest: str) -> str:
    return digest.split(":", 1)[1][:16]


def import_kits(entries: list, *, registry=None, cache_dir=None) -> list:
    """The report for each kit the recipe names: {ref, name, status included|excluded, reason, digest, review_hash, findings, facts}. A kit is included only when its manifest digest equals `reviewed`
    and every finding is in `accept`. With a cache folder, a kit read now is kept and one that cannot be reached is read from the copy (and says so)."""
    registry = registry or Registry()
    rows = []
    for entry in entries:
        row = {"ref": entry["ref"], "status": "excluded", "reason": "", "findings": [], "note": ""}
        rows.append(row)
        kit = None
        try:
            kit = fetch(entry["ref"], registry)
            if cache_dir is not None:
                _keep(Path(cache_dir), kit)
                row["note"] = "read now"
        except KitError as failure:
            if cache_dir is not None:
                kit = _kept(Path(cache_dir), entry["ref"])
            if kit is None:
                row["reason"] = f"it could not be read: {failure}"
                continue
            row["note"] = f"read from the copy kept earlier because: {failure}"
        try:
            found = review(kit["spec"])
        except KitError as bad:
            row["reason"] = str(bad)
            continue
        digest = short(kit["digest"])
        row.update(name=found["facts"]["name"], digest=kit["digest"], review_hash=digest, findings=found["findings"], facts=found["facts"])
        if entry.get("reviewed") != digest:
            row["reason"] = ("it has not been reviewed: read what it does below, then set reviewed to " if not entry.get("reviewed") else "it changed since it was reviewed: read it again, then set reviewed to ") + digest
            continue
        unaccepted = [f for f in found["findings"] if f not in set(entry.get("accept") or [])]
        if unaccepted:
            row["reason"] = "it needs a person to accept: " + ", ".join(unaccepted)
            continue
        row["status"] = "included"
    return rows


def _safe(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", ref)[:120]


def _keep(cache: Path, kit: dict) -> None:
    folder = cache / _safe(kit["ref"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "digest").write_text(kit["digest"])
    (folder / "spec.yaml").write_text(kit["spec"])
    for name, data in kit["files"].items():
        (folder / name).write_bytes(data)


def _kept(cache: Path, ref: str):
    folder = cache / _safe(ref)
    try:
        return {"ref": ref, "digest": (folder / "digest").read_text().strip(), "spec": (folder / "spec.yaml").read_text(), "files": {}}
    except OSError:
        return None
