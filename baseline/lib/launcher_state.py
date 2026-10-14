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
        "display_scale": {"label": "Display scale (%)", "type": "choice", "choices": [100, 125, 150, 200]},
        "default_run_mode": {"label": "Opens in", "type": "choice", "choices": list(ls.RUN_MODES)},
    }
    app_fields = {"enabled": {"label": "Wanted in this OS", "type": "boolean"},
                  "autostart": {"label": "Start with the OS", "type": "boolean"}}
    return {"os": os_fields, "app": app_fields}


def _settings(roots, os_id, app_ids):
    return {"os": ls.explain_os(roots, os_id), "apps": {key: ls.explain_app(roots, os_id, aid) for key, aid in app_ids.items()}}


def collect(vms: list, *, node: str, roots, os_id_for, app_id_for) -> dict:
    app_error = ""
    try:
        app_ids = {key: app_id_for(key) for key in APP_LABELS}
    except Exception as exc:       # noqa: BLE001 - an unavailable identifier registry must not hide the tiles
        app_ids, app_error = {}, f"application identifiers unavailable: {exc}"
    tiles = []
    for vm in vms:
        error, os_id = "", None
        try:
            os_id = os_id_for(vm)
        except Exception as exc:   # noqa: BLE001
            error = f"identifier unavailable: {exc}"
        tile = lm.build_tile(vm, os_id=os_id, node=node)
        tile["menu"] = lm.menu_for(tile)
        tile["details"] = [list(row) for row in lm.details(tile)]
        tile["paths"] = {}
        if tile["vmid"] is not None:
            for mode in tile["modes"]:
                if mode["enabled"]:
                    tile["paths"][mode["id"]] = lm.console_path("vm", tile["vmid"], tile["name"], node, mode["id"])
        tile["settings"] = None
        if os_id is not None and not error and not app_error:
            try:
                tile["settings"] = _settings(roots, os_id, app_ids)
            except ls.SettingsError as exc:
                error = str(exc)
        tile["settings_error"] = error or app_error
        tiles.append(tile)
    apps = [{"key": key, "label": label, "id": app_ids.get(key)} for key, label in APP_LABELS.items()]
    return {"host": node, "tiles": tiles, "apps": apps, "schema": schema()}
