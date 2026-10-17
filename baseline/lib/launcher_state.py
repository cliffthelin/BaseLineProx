"""Everything the launcher page is built from (DR259): tiles with their menus, details and console paths, and the settings of every OS and
application with the layer each value came from. A settings problem is reported on the tile; it never hides the tiles."""
from __future__ import annotations

import launcher_model as lm
import layered_settings as ls

APP_LABELS = {"vscode": "VS Code", "spotify": "Spotify", "chrome": "Chrome", "chatgpt": "ChatGPT", "claude": "Claude Desktop"}
_PATTERNS = {"timezone": ls._TIMEZONE.pattern, "locale": ls._LOCALE.pattern, "keyboard": ls._KEYBOARD.pattern}


def schema() -> dict:
    os_fields = {
        "timezone": {"label": "Time zone", "type": "text", "pattern": _PATTERNS["timezone"], "example": "America/Denver"},
        "locale": {"label": "Language and region", "type": "text", "pattern": _PATTERNS["locale"], "example": "en_US.UTF-8"},
        "keyboard": {"label": "Keyboard layout", "type": "text", "pattern": _PATTERNS["keyboard"], "example": "us"},
        "theme": {"label": "Appearance", "type": "choice", "choices": ["light", "dark", "auto"]},
        "display_scale": {"label": "Display scale (%)", "type": "choice", "choices": [100, 125, 150, 200], "numeric": True},
        "default_run_mode": {"label": "Opens in", "type": "choice", "choices": list(ls.RUN_MODES)},
        "swap_mb": {"label": "Swap (MB, 0 = none)", "type": "choice", "choices": list(ls.SWAP_MB_CHOICES), "numeric": True},
    }
    app_fields = {"enabled": {"label": "Wanted in this OS", "type": "boolean"},
                  "autostart": {"label": "Start with the OS", "type": "boolean"}}
    return {"os": os_fields, "app": app_fields}


def _settings(roots, os_id, app_ids):
    return {"os": ls.explain_os(roots, os_id), "apps": {key: ls.explain_app(roots, os_id, aid) for key, aid in app_ids.items()}}


def _tile(vm, kind, node, roots, id_for, app_ids, app_error):
    error, tile_id = "", None
    try:
        tile_id = id_for(vm)
    except Exception as exc:   # noqa: BLE001
        error = f"identifier unavailable: {exc}"
    tile = lm.build_tile(vm, os_id=tile_id, node=node, kind=kind)
    tile["menu"] = lm.menu_for(tile)
    tile["details"] = [list(row) for row in lm.details(tile)]
    tile["paths"] = {}
    if tile["vmid"] is not None:
        for mode in tile["modes"]:
            if mode["enabled"]:
                tile["paths"][mode["id"]] = lm.console_path(kind, tile["vmid"], tile["name"], node, mode["id"])
    tile["settings"] = None
    apps_needed = kind == "vm"
    if tile_id is not None and not error and not (apps_needed and app_error):
        try:
            tile["settings"] = _settings(roots, tile_id, app_ids if apps_needed else {})
        except ls.SettingsError as exc:
            error = str(exc)
    tile["settings_error"] = error or (app_error if apps_needed else "")
    return tile


def collect(vms: list, *, node: str, roots, os_id_for, app_id_for, containers=(), container_id_for=None, containers_error: str = "", available=()) -> dict:
    app_error = ""
    try:
        app_ids = {key: app_id_for(key) for key in APP_LABELS}
    except Exception as exc:       # noqa: BLE001 - an unavailable identifier registry must not hide the tiles
        app_ids, app_error = {}, f"application identifiers unavailable: {exc}"
    tiles = [_tile(vm, "vm", node, roots, os_id_for, app_ids, app_error) for vm in vms]
    tiles += [_tile(ct, "ct", node, roots, container_id_for, app_ids, app_error) for ct in (containers or ())]
    notices = [f"Containers unavailable: {containers_error}"] if containers_error else []
    apps = [{"key": key, "label": label, "id": app_ids.get(key)} for key, label in APP_LABELS.items()]
    return {"host": node, "tiles": tiles, "apps": apps, "schema": schema(), "notices": notices, "available": list(available)}
