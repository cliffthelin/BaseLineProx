"""The application catalogue and the helper that installs an application on a given system (DR266 item 4; operator 2026-10-17).

Each entry says, per kind of route, how the application is installed: from the system's own package repository (`apt`, `pacman`), declared in a NixOS configuration (`nix`), as a Flatpak
(`flatpak`, for Bazzite and anywhere the repository has no package), as a portable app inside a Kasm desktop (`proot`), or as a service container behind Kasm's web gateway (`container`).
`route_for` picks one for a system from that system's own order of preference; `install_script` writes the shell that does it (non-interactive, every value validated first, nothing taken from the
person's input). Where no route fits, the answer says so instead of choosing something unsafe.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

FORMAT = "baseline.app-catalogue/v1"
CATEGORIES = ("browsers", "developer-tools", "ai-tools", "media", "ai-image-tools", "office-tools")
ROUTES = ("apt", "deb", "pacman", "nix", "flatpak", "appimage", "service", "proot", "container", "web")
# What each system prefers first. Immutable and declarative systems have narrower choices; Ubuntu's repository packages for browsers are snaps, so it prefers Flatpak.
# `web` comes last everywhere (except Kasm, which has its own routes): an application that has no program for a system is opened as its own window of the website, in Chrome, signed in with the person's own Chrome profile.
PREFERENCE = {
    "debian": ("apt", "deb", "flatpak", "appimage", "service", "web"), "ubuntu": ("flatpak", "deb", "apt", "appimage", "service", "web"), "cachyos": ("pacman", "flatpak", "appimage", "service", "web"),
    "omarchy": ("pacman", "flatpak", "appimage", "service", "web"), "bazzite": ("flatpak", "appimage", "service", "web"), "nixos": ("nix", "flatpak", "web"), "kasm": ("proot", "container"),
}
# Publishers whose Debian package index (or fixed download) is read to find the current file; the index also gives the SHA-256 that is checked before the package is installed.
PUBLISHERS = {
    "spotify": {"base": "https://repository.spotify.com/", "index": "dists/stable/non-free/binary-amd64/Packages", "package": "spotify-client"},
    "claude": {"base": "https://downloads.claude.ai/claude-desktop/apt/stable/", "index": "dists/stable/main/binary-amd64/Packages", "package": "claude-desktop"},
    "chrome": {"base": "https://dl.google.com/linux/chrome/deb/", "index": "dists/stable/main/binary-amd64/Packages", "package": "google-chrome-stable"},
    "chatgpt": {"url": "https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_amd64.deb"},          # no index: its hash is recorded when first fetched
}
_APPIMAGE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,40}$")
_RELEASE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ASSET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
_ID = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,80}$")
_FLATPAK = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+){2,}$")
_NIX_ATTR = re.compile(r"^[a-z][A-Za-z0-9_.-]{0,60}$")
_IMAGE = re.compile(r"^[a-z0-9][a-z0-9./_-]{0,100}:[A-Za-z0-9_][A-Za-z0-9._-]{0,60}$")


class CatalogueError(ValueError):
    pass


def validate_entry(entry) -> dict:
    if not isinstance(entry, dict) or not _ID.match(str(entry.get("id", ""))) or entry.get("category") not in CATEGORIES or not str(entry.get("name", "")).strip():
        raise CatalogueError("an entry needs an id, a name and one of the known categories")
    routes = entry.get("routes")
    if not isinstance(routes, dict) or not routes or not set(routes) <= set(ROUTES):
        raise CatalogueError(f"{entry['id']}: routes are some of {', '.join(ROUTES)}")
    for route, params in routes.items():
        if not isinstance(params, dict):
            raise CatalogueError(f"{entry['id']}.{route}: parameters are an object")
        ok = {"apt": lambda p: _PACKAGE.match(str(p.get("package", ""))), "pacman": lambda p: _PACKAGE.match(str(p.get("package", ""))),
              "nix": lambda p: _NIX_ATTR.match(str(p.get("attr", ""))), "flatpak": lambda p: _FLATPAK.match(str(p.get("id", ""))),
              "proot": lambda p: _PACKAGE.match(str(p.get("name", ""))),
              "deb": lambda p: p.get("publisher") in PUBLISHERS,
              "appimage": lambda p: str(p.get("url", "")).startswith("https://") and not re.search(r"[\s'\"`$;&|<>\\]", str(p.get("url", ""))) and _APPIMAGE_NAME.match(str(p.get("name", ""))),
              "service": lambda p: _RELEASE.match(str(p.get("release", ""))) and _ASSET.match(str(p.get("asset", ""))) and isinstance(p.get("port"), int) and 1 <= p["port"] <= 65535
              and str(p.get("models", "")).startswith("/") and ".." not in str(p.get("models", "")) and not re.search(r"[\s'\"`$;&|<>\\]", str(p.get("models", ""))),
              "web": lambda p: re.fullmatch(r"https://[a-z0-9.-]+\.[a-z]{2,}(/[A-Za-z0-9._~/-]*)?", str(p.get("url", ""))) is not None,
              "container": lambda p: _IMAGE.match(str(p.get("image", ""))) and isinstance(p.get("ports"), list) and all(isinstance(x, int) and 1 <= x <= 65535 for x in p["ports"])
              and str(p.get("config", "")).startswith("/")}[route](params)
        if not ok:
            raise CatalogueError(f"{entry['id']}.{route}: a value is not a plain name")
        only = params.get("only")
        if only is not None and (not isinstance(only, list) or not all(o in PREFERENCE for o in only)):
            raise CatalogueError(f"{entry['id']}.{route}: only lists known systems")
    if "launch" in entry and not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,60}", str(entry["launch"])):
        raise CatalogueError(f"{entry['id']}: launch is the name of one command")
    data = entry.get("data", [])
    if not isinstance(data, list) or not all(isinstance(d, str) and d.startswith(("~/", "/")) and ".." not in d for d in data):
        raise CatalogueError(f"{entry['id']}: data paths are absolute or start with ~/")
    return entry


def load(path=None) -> dict:
    """{id: entry} from the catalogue file (default: config/app-catalogue.json beside the source), every entry validated and ids unique."""
    path = Path(path) if path else Path(__file__).resolve().parents[2] / "config" / "app-catalogue.json"
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CatalogueError(f"the application catalogue cannot be read: {exc}") from None
    if document.get("format") != FORMAT or not isinstance(document.get("apps"), list):
        raise CatalogueError(f"the catalogue has format {FORMAT} and a list of apps")
    out = {}
    for entry in document["apps"]:
        validate_entry(entry)
        if entry["id"] in out:
            raise CatalogueError(f"{entry['id']} is listed twice")
        out[entry["id"]] = entry
    return out


def route_for(entry: dict, os_id: str):
    """(route, params) for this system, or (None, reason). The system's own preference order decides; a route restricted with `only` is skipped elsewhere."""
    order = PREFERENCE.get(os_id)
    if order is None:
        return None, f"{os_id} is not a system this catalogue knows"
    for route in order:
        params = entry["routes"].get(route)
        if params is not None and os_id in (params.get("only") or [os_id]):
            return route, params
    return None, f"{entry['name']} has no route that fits {os_id} (it offers: {', '.join(sorted(entry['routes']))})"


FLATHUB = "https://dl.flathub.org/repo/flathub.flatpakrepo"
# `apt-get update` exits non-zero when ANY source cannot be read (a leftover installer-medium line, a third-party repository that is down), though the lists that matter were fetched; the install that
# follows is what must succeed, so an update error is reported and not fatal.
_APT_UPDATE = 'apt-get update || echo "apt-get update reported errors; going on to the install" >&2'
_FLATPAK_FIRST = {"debian": _APT_UPDATE + "\napt-get install -y flatpak", "ubuntu": _APT_UPDATE + "\napt-get install -y flatpak", "cachyos": "pacman -Syu --noconfirm --needed flatpak", "omarchy": "pacman -Syu --noconfirm --needed flatpak",
                  "bazzite": "command -v flatpak >/dev/null"}


def install_script(entry: dict, os_id: str, resolved: dict = None):
    """The shell that installs the application on this system, or None where the route is not an install-time command (nix is declared in the configuration; proot and container belong to the Kasm
    and service-host sides). Non-interactive and fail-fast. The `deb`, `appimage` and `service` routes download a file: `resolved` (from `resolve`) names the exact file and the SHA-256 to check; without
    one the script still downloads the current file, records its SHA-256 in /var/lib/baseline/app-hashes (the first fetch becomes the reference) and says so."""
    route, params = route_for(entry, os_id)
    if route is None:
        raise CatalogueError(params)
    head = ["#!/bin/sh", "set -eu", "export DEBIAN_FRONTEND=noninteractive"]
    if route == "apt":
        return "\n".join(head + [_APT_UPDATE, f"apt-get install -y {params['package']}"]) + "\n"
    if route == "pacman":
        return "\n".join(head + [f"pacman -Syu --noconfirm --needed {params['package']}"]) + "\n"
    if route == "flatpak":
        prerequisite = _FLATPAK_FIRST.get(os_id)
        return "\n".join(head + ([prerequisite] if prerequisite else []) + [f"flatpak remote-add --if-not-exists --system flathub {FLATHUB}", f"flatpak install -y --system --noninteractive flathub {params['id']}"]) + "\n"
    if route in ("deb", "appimage", "service"):
        return "\n".join(head + _download_lines(entry, route, params, resolved or {})) + "\n"
    if route == "web":
        return "\n".join(head + _web_lines(entry, params)) + "\n"
    return None


def web_command(entry_id: str) -> str:
    return f"baseline-web-{entry_id}"


def _web_lines(entry: dict, params: dict) -> list:
    """The application as its own window of the website, in Chrome (the program the person signs in to once); started with the password store every machine shares, so the shared sign-in opens."""
    key, url = entry["id"], params["url"]
    command = web_command(key)
    run = (f'if command -v google-chrome-stable >/dev/null 2>&1; then exec google-chrome-stable --password-store=basic --app={url} "$@"; '
           f'else exec flatpak run com.google.Chrome --password-store=basic --app={url} "$@"; fi')
    return [f"cat > /usr/local/bin/{command} <<'WRAPPER'", "#!/bin/sh", run, "WRAPPER", f"chmod 0755 /usr/local/bin/{command}", "mkdir -p /usr/local/share/applications",
            f"cat > /usr/local/share/applications/{command}.desktop <<'ENTRY'", "[Desktop Entry]", "Type=Application", f"Name={entry['name']}", f"Exec=/usr/local/bin/{command}", "Categories=Network;", "ENTRY"]


# A freshly built base has no package lists and may have no curl: fetch both before anything is downloaded, whichever package manager the system has.
_NEED_CURL = ('command -v curl >/dev/null || { if command -v apt-get >/dev/null; then ' + _APT_UPDATE.replace("\n", " ") + '; apt-get install -y curl ca-certificates; '
              'elif command -v pacman >/dev/null; then pacman -Syu --noconfirm --needed curl; fi; }')


def _fetch_and_check(url: str, target: str, sha256: str, key: str) -> list:
    lines = [_NEED_CURL, "mkdir -p /var/lib/baseline/app-hashes", f"curl -fL --proto '=https' --tlsv1.2 -o {target} '{url}'"]
    if sha256:
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise CatalogueError("a SHA-256 is 64 lowercase hex characters")
        lines.append(f"echo '{sha256}  {target}' | sha256sum -c -")
    else:
        lines += [f"sha256sum {target} | cut -d' ' -f1 > /var/lib/baseline/app-hashes/{key}", f"echo 'no hash was pinned for {key}; recorded' \"$(cat /var/lib/baseline/app-hashes/{key})\" 'as the reference' >&2"]
    return lines


def _download_lines(entry: dict, route: str, params: dict, resolved: dict) -> list:
    key = entry["id"]
    url = resolved.get("url") or (PUBLISHERS[params["publisher"]].get("url") if route == "deb" else params.get("url"))
    if route == "deb":
        if not url:
            raise CatalogueError(f"{entry['name']}: its package must be resolved first (resolve) so the file and its hash are named")
        return _fetch_and_check(url, "/tmp/app.deb", resolved.get("sha256", ""), key) + ["apt-get install -y /tmp/app.deb", "rm -f /tmp/app.deb"]
    if route == "appimage":
        name = params["name"]
        return (_fetch_and_check(url, f"/tmp/{name}.AppImage", resolved.get("sha256", ""), key)
                + ["if command -v apt-get >/dev/null; then apt-get install -y libfuse2t64 2>/dev/null || apt-get install -y libfuse2 2>/dev/null || true; fi", "mkdir -p /opt/appimages",
                   f"install -m 0755 /tmp/{name}.AppImage /opt/appimages/{name}.AppImage", f"rm -f /tmp/{name}.AppImage",
                   f"printf '#!/bin/sh\\nexec /opt/appimages/{name}.AppImage --appimage-extract-and-run \"$@\"\\n' > /usr/local/bin/{key}", f"chmod 0755 /usr/local/bin/{key}"])
    # a systemd service from a release tarball (Ollama): extracted under /opt, run by its own unprivileged user, data on the mount named in the entry
    models, port = params["models"], params["port"]
    if not url:
        raise CatalogueError(f"{entry['name']}: its release must be resolved first (resolve) so the file and its hash are named")
    return (["if command -v apt-get >/dev/null; then " + _APT_UPDATE + "; apt-get install -y zstd; elif command -v pacman >/dev/null; then pacman -Syu --noconfirm --needed zstd; fi"]
            + _fetch_and_check(url, "/tmp/service.tar.zst", resolved.get("sha256", ""), key)
            + [f"mkdir -p /opt/{key}", f"zstd -dc /tmp/service.tar.zst | tar -x -C /opt/{key}", "rm -f /tmp/service.tar.zst",
               f"ln -sf /opt/{key}/bin/{key} /usr/local/bin/{key}",
               f"id {key} >/dev/null 2>&1 || useradd --system --home-dir {models} --shell /usr/sbin/nologin {key}",
               f"mkdir -p {models}", f"chown {key}: {models}",
               f"cat > /etc/systemd/system/{key}.service <<'UNIT'", "[Unit]", f"Description={entry['name']} server", "After=network-online.target", "Wants=network-online.target", "RequiresMountsFor=" + models,
               "[Service]", f"ExecStart=/opt/{key}/bin/{key} serve", f"User={key}", f"Group={key}", f"Environment=OLLAMA_HOST=0.0.0.0:{port}" if key == "ollama" else f"Environment=PORT={port}",
               f"Environment=OLLAMA_MODELS={models}" if key == "ollama" else f"Environment=DATA_DIR={models}", "Restart=always", "RestartSec=3", "[Install]", "WantedBy=multi-user.target", "UNIT",
               "systemctl daemon-reload", f"systemctl enable --now {key}"])


# ---- finding the exact file (done on the machine with the network, before the script is written) -------------------------------------------------------
def _http_get(opener, url, limit=32 * 1024 * 1024, headers=None):
    import urllib.request
    request = urllib.request.Request(url, headers={"User-Agent": "baseline-app-catalogue", **(headers or {})})
    try:
        with opener(request, timeout=30) as response:
            data = response.read(limit + 1)
            return data, getattr(response, "url", url) if not hasattr(response, "geturl") else response.geturl()
    except OSError as exc:
        raise CatalogueError(f"could not read {url}: {exc}") from None


def resolve(entry: dict, os_id: str, opener=None) -> dict:
    """{url, sha256?, version?} for a route that downloads a file, found from the publisher's own index or release data: a Debian package index (its SHA-256 and filename), a GitHub release asset
    (its published SHA-256), or the versioned address a download link redirects to (no hash is published: the script records one). {} for routes that download nothing."""
    import urllib.request
    opener = opener or urllib.request.urlopen
    route, params = route_for(entry, os_id)
    if route == "deb":
        publisher = PUBLISHERS[params["publisher"]]
        if "url" in publisher:
            return {"url": publisher["url"]}
        data, _ = _http_get(opener, publisher["base"] + publisher["index"])
        best = None
        for stanza in data.decode("utf-8", "replace").split("\n\n"):
            fields = dict(line.split(": ", 1) for line in stanza.splitlines() if ": " in line and not line.startswith(" "))
            if fields.get("Package") == publisher["package"] and fields.get("Architecture") == "amd64" and re.fullmatch(r"[A-Za-z0-9.+:~_-]{1,128}", fields.get("Version", "")):
                if best is None or _newer(fields["Version"], best["Version"]):
                    best = fields
        if best is None or not best.get("Filename") or not re.fullmatch(r"[0-9a-f]{64}", best.get("SHA256", "")):
            raise CatalogueError(f"{entry['name']}: the publisher's index has no usable package")
        return {"url": publisher["base"] + best["Filename"], "sha256": best["SHA256"], "version": best["Version"]}
    if route == "service":
        import json as _json
        data, _ = _http_get(opener, f"https://api.github.com/repos/{params['release']}/releases/latest", headers={"Accept": "application/vnd.github+json"})
        release = _json.loads(data.decode())
        asset = next((a for a in release.get("assets", []) if a.get("name") == params["asset"]), None)
        digest = str((asset or {}).get("digest", ""))
        if asset is None or not digest.startswith("sha256:") or not re.fullmatch(r"[0-9a-f]{64}", digest[7:]):
            raise CatalogueError(f"{entry['name']}: the release has no {params['asset']} with a published SHA-256")
        return {"url": asset["browser_download_url"], "sha256": digest[7:], "version": release.get("tag_name", "")}
    if route == "appimage":
        request = urllib.request.Request(params["url"], method="HEAD", headers={"User-Agent": "baseline-app-catalogue"})
        try:
            with opener(request, timeout=30) as response:
                final = response.geturl() if hasattr(response, "geturl") else params["url"]
        except OSError as exc:
            raise CatalogueError(f"could not read {params['url']}: {exc}") from None
        return {"url": final}
    return {}


def _newer(a: str, b: str) -> bool:
    import subprocess
    return subprocess.run(["dpkg", "--compare-versions", a, "gt", b], capture_output=True).returncode == 0


def nix_attrs(entries) -> list:
    """The nixpkgs attributes for the applications that have a nix route, for a NixOS configuration's systemPackages."""
    return [e["routes"]["nix"]["attr"] for e in entries if "nix" in e["routes"]]
