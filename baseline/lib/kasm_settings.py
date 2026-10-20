"""Kasm's server settings as Baseline builds them (DR260; operator 2026-10-17: Baseline supports the 87 settings and can build them from scratch).

Kasm documents "slip-stream install configurations": the installer is given your own `conf/database/seed_data/default_properties.yaml` (the same format as its export), and Kasm's OWN
installer seeds and encrypts it. So Baseline writes plain, typed settings into that seed and never touches Kasm's encryption: it neither needs nor holds Kasm's keys, and what it
builds stays compatible with whatever Kasm does with them. (Kasm's licence forbids reverse-engineering its software; this is the documented way, and the only one used.)

The release's own seed is the catalogue: each setting has a name, a category, a title, a type, a default, whether it is a secret (`sanitize` or type `password`), and which services
need a restart when it changes. Overrides are checked against that: an unknown name is refused, a value must fit its type, and a secret is never overridden here (secrets stay
generated at install time by Kasm's own `${random_token...}`/`${rsa...}` templates).
"""
from __future__ import annotations

import json

import yaml

TYPES = ("bool", "int", "float", "string", "String", "multiline_string", "password", "select", "json")


class SettingsError(ValueError):
    pass


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def catalogue(seed_text: str) -> list:
    """Every server setting the release seeds, in a stable shape."""
    document = yaml.safe_load(seed_text) or {}
    out = []
    for row in document.get("settings", []):
        restart = [s for s in str(row.get("services_restart") or "").split(",") if s and s != "None"]
        out.append({"name": row["name"], "category": row.get("category", ""), "title": row.get("title", ""), "type": row.get("value_type", "string"),
                    "default": "" if row.get("value") is None else str(row["value"]), "secret": _truthy(row.get("sanitize")) or row.get("value_type") == "password",
                    "restart": restart, "description": row.get("description", "")})
    return out


_SECRET_NAME = __import__("re").compile(r"(?i)(^token$|_token$|_secret$|_password$|_passwd$|private|priv_key$|api_key$|secret_key$)")
_PRIVATE_KEY_PEM = __import__("re").compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


def looks_secret(name: str, value_type: str = "", value=None) -> bool:
    """Whether a setting must be treated as a secret when Kasm does not say. Kasm's own `get_settings` carries no `sanitize` flag (found 2026-10-17: a private key would have passed as an ordinary
    value), so a setting is a secret if its type is `password`, its name ends in a secret-like word or names a private key, or its value is PEM PRIVATE key material. Public certificates, a public
    site key, an access key ID and the password-policy numbers are not secrets and stay visible; every one of the nine the release marks as secret is caught (tested against its own list)."""
    return value_type == "password" or bool(_SECRET_NAME.search(name or "")) or bool(_PRIVATE_KEY_PEM.search(str(value or "")))


def normalise(setting: dict, value) -> str:
    """The text Kasm stores for `value`, if it fits the setting's type."""
    kind, name = setting["type"], setting["name"]
    text = str(value)
    if kind == "bool":
        if str(value).strip().lower() not in ("true", "false"):
            raise SettingsError(f"{name} is true or false")
        return "True" if str(value).strip().lower() == "true" else "False"
    if kind == "int":
        try:
            return str(int(text))
        except ValueError:
            raise SettingsError(f"{name} is a whole number") from None
    if kind == "float":
        try:
            return str(float(text))
        except ValueError:
            raise SettingsError(f"{name} is a number") from None
    if kind == "json":
        try:
            json.loads(text)
        except ValueError:
            raise SettingsError(f"{name} is JSON") from None
    return text


def apply_overrides(seed_text: str, overrides: dict) -> tuple:
    """(new seed text, [{name, from, to, restart}]) with `overrides` applied by name. Refuses unknown names, ill-typed values and secrets."""
    if not isinstance(overrides, dict):
        raise SettingsError("settings overrides are a name to value mapping")
    document = yaml.safe_load(seed_text) or {}
    by_name = {row["name"]: row for row in document.get("settings", [])}
    known = {entry["name"]: entry for entry in catalogue(seed_text)}
    changes = []
    for name, value in overrides.items():
        if name not in known:
            raise SettingsError(f"{name} is not a setting this Kasm release has")
        if known[name]["secret"]:
            raise SettingsError(f"{name} is a secret; it is generated when Kasm installs, never set from a recipe")
        new = normalise(known[name], value)
        old = by_name[name].get("value")
        by_name[name]["value"] = new
        changes.append({"name": name, "from": None if old is None else str(old), "to": new, "restart": known[name]["restart"]})
    return yaml.safe_dump(document, sort_keys=False, default_flow_style=False, width=10_000, allow_unicode=True), changes


def summary(catalog: list) -> dict:
    """A report (not a table): how the settings divide up, for a person to read."""
    categories: dict = {}
    for entry in catalog:
        categories.setdefault(entry["category"], 0)
        categories[entry["category"]] += 1
    return {"settings": len(catalog), "secrets": sum(1 for e in catalog if e["secret"]), "need_restart": sum(1 for e in catalog if e["restart"]), "categories": categories}
