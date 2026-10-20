"""Sign in once, be signed in everywhere (operator, 2026-10-19: no sign-in reached the browser, so Google and Claude had to be set up by hand on each machine).

An application keeps its sign-in in a few small files (Chrome: the cookies, saved logins and preferences of its profile; Claude: its cookies and the Claude Code credentials; ChatGPT: its
auth file). `capture` reads those files from a machine where the person is signed in, `Store` keeps them with the person's other secrets (sealed with the vault's passphrase whenever the
vault has one), and `apply` places them for the owner on a machine that is not signed in yet. A machine that already has a sign-in is never overwritten, a bundle can only name the files listed
here, and nothing leaves the person's own volumes.

What it cannot promise: Chrome and Claude encrypt cookie values with a key from the machine's password store. Every machine Baseline makes starts them with `--password-store=basic` (a fixed key,
the same everywhere), so the copied cookies open; and a site such as Google may still ask for its own check on a new machine, which only the person can answer.
"""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path

import vault_crypto

_ACCOUNT = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_REL = re.compile(r"^[A-Za-z0-9 ._-]+(/[A-Za-z0-9 ._-]+)*$")
_BROWSER_FILES = ["Default/Cookies", "Default/Login Data", "Default/Login Data For Account", "Default/Web Data", "Default/Preferences", "Local State"]
MAX_FILE = 8 * 1024 * 1024

SETS = {
    "chrome": [{"roots": (".config/google-chrome", ".var/app/com.google.Chrome/config/google-chrome"), "probe": "google-chrome-stable", "files": _BROWSER_FILES, "marker": "Default/Cookies"}],
    "chromium": [{"roots": (".config/chromium", ".var/app/org.chromium.Chromium/config/chromium"), "probe": "chromium", "files": _BROWSER_FILES, "marker": "Default/Cookies"}],
    "claude": [{"roots": (".config/Claude",), "probe": None, "files": ["Cookies", "Network/Cookies", "config.json", "Local State"], "marker": "config.json"},
               {"roots": (".claude",), "probe": None, "files": [".credentials.json"], "marker": ".credentials.json"}],
    "chatgpt": [{"roots": (".codex",), "probe": None, "files": ["auth.json"], "marker": "auth.json"}],
}
LABELS = {"chrome": "Google Chrome", "chromium": "Chromium", "claude": "Claude", "chatgpt": "ChatGPT"}

# Started with a password store every machine shares, so one machine's encrypted cookies open on another (see the module note). Only the real program's path differs.
_WRAPPED = {"chrome": ("google-chrome-stable", "/opt/google/chrome/google-chrome"), "chromium": ("chromium", "/usr/bin/chromium"),
            "claude": ("claude-desktop", "/usr/lib/claude-desktop/claude-desktop")}
_DESKTOP = {"chrome": ("/usr/local/share/applications/google-chrome.desktop", "Google Chrome", "google-chrome", "Network;WebBrowser;")}


class SigninError(ValueError):
    pass


class Locked(SigninError):
    """The sealed sign-ins need the vault's passphrase."""


def wrapper_files(app: str) -> list:
    """cloud-init write_files entries that start `app` with the shared password store (none for an application that does not need it)."""
    if app not in _WRAPPED:
        return []
    command, real = _WRAPPED[app]
    files = [{"path": f"/usr/local/bin/{command}", "permissions": "0755", "content": f'#!/bin/sh\nexec {real} --password-store=basic "$@"\n'}]
    if app in _DESKTOP:
        path, name, icon, categories = _DESKTOP[app]
        files.append({"path": path, "permissions": "0644", "content": f"[Desktop Entry]\nType=Application\nName={name}\nIcon={icon}\nExec=/usr/local/bin/{command} %U\nCategories={categories}\nStartupNotify=true\n"})
    return files


def _account(owner) -> str:
    if not isinstance(owner, str) or not _ACCOUNT.fullmatch(owner):
        raise SigninError("the owner is a plain account name")
    return owner


def _groups(app):
    if app not in SETS:
        raise SigninError(f"{app} has no sign-in files Baseline knows")
    return SETS[app]


def _root_here(exec_, home, group, *, existing: bool):
    """Which of the group's folders this machine uses: the one that already holds the marker (capture), or the one matching how the program is installed (apply)."""
    roots = group["roots"]
    if len(roots) == 1:
        return roots[0]
    if existing:
        for root in roots:
            try:
                exec_(["test", "-e", f"{home}/{root}/{group['marker']}"])
                return root
            except Exception:
                continue
        return None
    probe = group["probe"]
    kind = exec_(["sh", "-c", f"if command -v {probe} >/dev/null 2>&1; then echo deb; else echo flatpak; fi"]).strip()
    return roots[0] if kind == "deb" else roots[1]


def capture(exec_, owner, app, *, source) -> dict:
    """Read the sign-in files of `app` from a machine where the owner is signed in. `exec_(argv, data=b"")` runs a command on that machine as root and returns its output."""
    home = f"/home/{_account(owner)}"
    found = []
    for index, group in enumerate(_groups(app)):
        root = _root_here(exec_, home, group, existing=True)
        if root is None:
            continue
        for rel in group["files"]:
            try:
                encoded = exec_(["base64", "-w0", "--", f"{home}/{root}/{rel}"]).strip()
            except Exception:
                continue                                  # a file that is not there is not part of this sign-in
            if len(encoded) > MAX_FILE * 4 // 3 + 8:
                continue
            found.append({"group": index, "path": rel, "b64": encoded})
    if not any(f["path"] == _groups(app)[f["group"]]["marker"] for f in found):
        raise SigninError(f"nobody is signed in to {LABELS.get(app, app)} on that machine")
    return {"app": app, "from": str(source)[:64], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "files": found}


def apply(exec_, owner, bundle, *, force=False) -> dict:
    """Place a captured sign-in for the owner. Returns {"applied": [paths], "skipped": reason|""}; never replaces a sign-in the machine already has unless `force`."""
    home = f"/home/{_account(owner)}"
    groups = _groups(bundle.get("app") if isinstance(bundle, dict) else None)
    files = bundle.get("files")
    if not isinstance(files, list):
        raise SigninError("the saved sign-in is damaged")
    checked = []
    for item in files:
        if (not isinstance(item, dict) or not isinstance(item.get("group"), int) or not 0 <= item["group"] < len(groups) or not isinstance(item.get("path"), str)
                or not _REL.fullmatch(item["path"]) or ".." in item["path"].split("/") or item["path"] not in groups[item["group"]]["files"]):
            raise SigninError("the saved sign-in names a file it may not")
        try:
            data = base64.b64decode(item.get("b64", ""), validate=True)
        except (ValueError, TypeError):
            raise SigninError("the saved sign-in is damaged") from None
        if len(data) > MAX_FILE:
            raise SigninError("the saved sign-in has a file that is too large")
        checked.append((item["group"], item["path"], data))
    report = {"applied": [], "skipped": ""}
    placed_groups = set()
    for index, group in enumerate(groups):
        mine = [(path, data) for g, path, data in checked if g == index]
        if not mine:
            continue
        root = _root_here(exec_, home, group, existing=False)
        if not force:
            try:
                exec_(["test", "-e", f"{home}/{root}/{group['marker']}"])
                report["skipped"] = "already signed in on this machine"
                continue
            except Exception:
                pass
        for path, data in mine:
            target = f"{home}/{root}/{path}"
            exec_(["runuser", "-u", owner, "--", "sh", "-c", 'umask 077; mkdir -p "$(dirname "$1")"; cat > "$1"', "sh", target], data)
            report["applied"].append(path)
        placed_groups.add(index)
    return report


class Store:
    """Captured sign-ins, one file per application in a folder only its owner can enter. Sealed with the vault's passphrase when one is given (and refused when the vault is sealed but its
    passphrase is not at hand: a sign-in is never kept in the clear beside a vault that is sealed)."""

    def __init__(self, folder, passphrase=None, must_seal=False):
        self.folder, self.passphrase, self.must_seal = Path(folder), passphrase, must_seal

    def _check(self, app):
        if app not in SETS:
            raise SigninError("unknown application")

    def save(self, bundle: dict) -> None:
        self._check(bundle.get("app"))
        if self.passphrase is None and self.must_seal:
            raise Locked("the vault is sealed; unlock it first so the sign-in can be kept sealed too")
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.folder.chmod(0o700)
        text = json.dumps(bundle)
        name, content = (f"{bundle['app']}.sealed", vault_crypto.seal(text, self.passphrase)) if self.passphrase else (f"{bundle['app']}.json", text)
        target = self.folder / name
        target.write_text(content)
        target.chmod(0o600)
        (self.folder / (f"{bundle['app']}.json" if self.passphrase else f"{bundle['app']}.sealed")).unlink(missing_ok=True)

    def load(self, app: str) -> dict:
        self._check(app)
        sealed, plain = self.folder / f"{app}.sealed", self.folder / f"{app}.json"
        if sealed.is_file():
            if self.passphrase is None:
                raise Locked("the vault's passphrase is needed to open the saved sign-ins")
            return json.loads(vault_crypto.open_sealed(sealed.read_text(), self.passphrase))
        if plain.is_file():
            return json.loads(plain.read_text())
        raise SigninError(f"no sign-in is saved for {LABELS.get(app, app)}")

    def apps(self) -> list:
        if not self.folder.is_dir():
            return []
        return sorted({p.stem for p in self.folder.iterdir() if p.suffix in (".json", ".sealed") and p.stem in SETS})

    def forget(self, app: str) -> None:
        self._check(app)
        for suffix in (".json", ".sealed"):
            (self.folder / f"{app}{suffix}").unlink(missing_ok=True)


# ---- across the machines this host runs ------------------------------------------------------------------------------------------------------------------
def guest_exec_for(host, name):
    """exec_ for one virtual machine: its guest agent, as root; a command that fails raises (the host's own refusal included)."""
    def run(argv, data=b""):
        result = host.guest_exec(name, argv, data)
        return result.get("out-data", "") if isinstance(result, dict) else ""
    return run


def capture_from(host, store, owner, app, vm) -> dict:
    bundle = capture(guest_exec_for(host, vm), owner, app, source=vm)
    store.save(bundle)
    return {"app": app, "from": vm, "files": len(bundle["files"])}


def apply_to_running(host, store, owner, *, apps=None, force=False) -> dict:
    """Place every saved sign-in on every running machine that has none. {machine: {app: {"applied": [...], "skipped": "..."} | {"error": "..."}}}. One machine or application failing does not stop
    the others; a machine without a running guest agent is reported, not fatal."""
    report = {}
    saved = [a for a in store.apps() if apps is None or a in apps]
    for vm in host.list_vms():
        if not vm.get("running"):
            continue
        exec_ = guest_exec_for(host, vm["name"])
        report[vm["name"]] = {}
        for app in saved:
            try:
                report[vm["name"]][app] = apply(exec_, owner, store.load(app), force=force)
            except Locked:
                raise
            except Exception as exc:
                report[vm["name"]][app] = {"error": str(exc)[:160]}
    return report
