"""Settings shared from one OS to the next, in layers, stored only on the volumes that may hold non-public data (DR259).

    admin    USER_ADMIN/settings/shared.json                        host-wide defaults; an administrator writes it, nothing else does
    user     USER_<PERSONA>/settings/shared.json                    the person's settings, shared by every OS
    os       USER_<PERSONA>/settings/os/<O_V_NNNNN>.json            the person's differences for one OS
    app      APPDATA_<PERSONA>/<A_x_NNNNN>/os/<O_V_NNNNN>.json      one application's settings in one OS
    session  SESSION_TEMP/launcher/session.json                     non-persistent

Effective settings for an OS are admin, then user, then os (later wins); for an application, those and then the app layer. A guest never
writes to USER_ADMIN (DR257). Keys are an allowlist with validated values; entities are named by their constant identifiers, never by a
name; nothing is ever written outside the four volumes, and a volume that is not mounted is refused instead of written through to the
disposable substrate. This stores settings; applying them inside a guest is a separate piece that does not exist yet.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from typing import NamedTuple

import naming

LAYERS = ("admin", "user", "os", "app", "session")
RUN_MODES = ("console", "window", "fullscreen")

_TIMEZONE = re.compile(r"^(UTC|[A-Za-z]+(/[A-Za-z0-9_+-]+){1,2})$")
_LOCALE = re.compile(r"^[a-z]{2,3}_[A-Z]{2}\.UTF-8$")
_KEYBOARD = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{1,8})?$")


def _one_of(*allowed):
    return lambda v: v if v in allowed else None


def _matching(pattern):
    return lambda v: v if isinstance(v, str) and pattern.fullmatch(v) else None


def _boolean(v):
    return v if isinstance(v, bool) else None


SWAP_MB_CHOICES = (0, 256, 512, 1024, 2048, 4096, 8192, 16384)      # a guest's swap; 0 is none
HOST_SWAP_KINDS = ("file", "reserved")                              # written once into SESSION_TEMP, or a regular volume that only reserves the space
HOST_SWAP_MAX_GIB = 64

SHARED_KEYS = {
    "timezone": _matching(_TIMEZONE),
    "locale": _matching(_LOCALE),
    "keyboard": _matching(_KEYBOARD),
    "theme": _one_of("light", "dark", "auto"),
    "display_scale": lambda v: v if (isinstance(v, int) and not isinstance(v, bool) and v in (100, 125, 150, 200)) else None,
    "default_run_mode": _one_of(*RUN_MODES),
    "swap_mb": lambda v: v if (isinstance(v, int) and not isinstance(v, bool) and v in SWAP_MB_CHOICES) else None,
}
# The host's own swap is not a guest setting: only the admin layer carries it, and only an administrator writes that layer.
ADMIN_ONLY_KEYS = {
    "host_swap_gib": lambda v: v if (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= HOST_SWAP_MAX_GIB) else None,
    "host_swap_kind": _one_of(*HOST_SWAP_KINDS),
}
APP_KEYS = {"enabled": _boolean, "autostart": _boolean}
_KEYS = {"admin": {**SHARED_KEYS, **ADMIN_ONLY_KEYS}, "user": SHARED_KEYS, "os": SHARED_KEYS, "session": SHARED_KEYS, "app": APP_KEYS}


class SettingsError(RuntimeError):
    pass


class Roots(NamedTuple):
    admin: str
    user: str
    appdata: str
    session: str
    require_mount: bool = False


def default_roots(persona: str) -> Roots:
    import appdata
    import drive_installer
    return Roots(admin="/mnt/USER_ADMIN", user=drive_installer.persona_mountpoint(persona), appdata=appdata.appdata_root(persona),
                 session="/mnt/SESSION_TEMP", require_mount=True)


def _identifier(value, cluster: str, what: str) -> str:
    if not isinstance(value, str) or not naming.is_id(value) or naming.parse_id(value).cluster != cluster:
        raise SettingsError(f"{what} must be a constant identifier of the {naming.CLUSTERS[cluster]} cluster, not {value!r}")
    return value


def _volume_and_path(roots: Roots, layer: str, os_id, app_id):
    if layer == "admin":
        return roots.admin, ("settings", "shared.json")
    if layer == "user":
        return roots.user, ("settings", "shared.json")
    if layer == "session":
        return roots.session, ("launcher", "session.json")
    if layer == "os":
        return roots.user, ("settings", "os", _identifier(os_id, "O", "an OS") + ".json")
    if layer == "app":
        return roots.appdata, (_identifier(app_id, "A", "an application"), "os", _identifier(os_id, "O", "an OS") + ".json")
    raise SettingsError(f"unknown settings layer {layer!r}")


def layer_path(roots: Roots, layer: str, *, os_id=None, app_id=None) -> str:
    volume, parts = _volume_and_path(roots, layer, os_id, app_id)
    return os.path.join(volume, *parts)


def _check_volume(roots: Roots, volume: str) -> str:
    if not os.path.isdir(volume):
        raise SettingsError(f"{volume} does not exist: the volume is not mounted, so nothing is written")
    if roots.require_mount and not os.path.ismount(volume):
        raise SettingsError(f"{volume} is not mounted: writing now would land on the disposable substrate")
    return os.path.realpath(volume)


def _inside(real_volume: str, path: str) -> bool:
    real = os.path.realpath(path)
    return real == real_volume or real.startswith(real_volume + os.sep)


def _validated(layer: str, data) -> dict:
    if not isinstance(data, dict):
        raise SettingsError(f"the {layer} settings are not a set of key/value pairs")
    checks, clean = _KEYS[layer], {}
    for key, value in data.items():
        if key not in checks:
            raise SettingsError(f"{key!r} is not a setting of the {layer} layer")
        ok = checks[key](value)
        if ok is None:
            raise SettingsError(f"{value!r} is not a valid value for {key}")
        clean[key] = ok
    return clean


def read_layer(roots: Roots, layer: str, *, os_id=None, app_id=None) -> dict:
    volume, parts = _volume_and_path(roots, layer, os_id, app_id)
    path = os.path.join(volume, *parts)
    if not os.path.isdir(volume):
        return {}
    if not _inside(os.path.realpath(volume), path):
        raise SettingsError(f"{path} resolves outside {volume}")
    try:
        with open(path, encoding="utf8") as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise SettingsError(f"{path} is unreadable: {exc}") from exc
    return _validated(layer, data)


def write_layer(roots: Roots, layer: str, changes: dict, *, os_id=None, app_id=None, actor: str = "person") -> dict:
    if layer == "admin" and actor != "admin":
        raise SettingsError("only an administrator may change the admin settings")
    if not isinstance(changes, dict) or not changes:
        raise SettingsError("no settings were given")
    volume, parts = _volume_and_path(roots, layer, os_id, app_id)
    removals = {k for k, v in changes.items() if v is None and k in _KEYS[layer]}
    updates = _validated(layer, {k: v for k, v in changes.items() if k not in removals})
    real_volume = _check_volume(roots, volume)
    path = os.path.join(volume, *parts)
    directory = os.path.dirname(path)
    if not _inside(real_volume, directory):
        raise SettingsError(f"{directory} resolves outside {volume}; refusing to write")
    current = read_layer(roots, layer, os_id=os_id, app_id=app_id)
    merged = {k: v for k, v in {**current, **updates}.items() if k not in removals}
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(merged, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return merged


def effective_os(roots: Roots, os_id: str) -> dict:
    _identifier(os_id, "O", "an OS")
    merged = {k: v for k, v in read_layer(roots, "admin").items() if k not in ADMIN_ONLY_KEYS}     # host-only settings are not a guest's
    merged.update(read_layer(roots, "user"))
    merged.update(read_layer(roots, "os", os_id=os_id))
    return merged


def effective_app(roots: Roots, os_id: str, app_id: str) -> dict:
    merged = effective_os(roots, os_id)
    merged.update(read_layer(roots, "app", os_id=os_id, app_id=app_id))
    return merged


def explain_os(roots: Roots, os_id: str) -> dict:
    """Effective OS settings with the layer each value came from, so a person can see what is inherited and what is their own."""
    _identifier(os_id, "O", "an OS")
    view = {}
    for layer, data in (("admin", read_layer(roots, "admin")), ("user", read_layer(roots, "user")),
                        ("os", read_layer(roots, "os", os_id=os_id))):
        for key, value in data.items():
            if layer == "admin" and key in ADMIN_ONLY_KEYS:
                continue
            view[key] = {"value": value, "source": layer}
    return view


def explain_app(roots: Roots, os_id: str, app_id: str) -> dict:
    view = explain_os(roots, os_id)
    for key, value in read_layer(roots, "app", os_id=os_id, app_id=app_id).items():
        view[key] = {"value": value, "source": "app"}
    return view
