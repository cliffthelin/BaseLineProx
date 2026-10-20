"""Kasm's server settings, built from its own seed (slip-stream): catalogue, typed overrides, secrets never set, everything else left exactly as the release has it."""
import re

import pytest
import yaml

import kasm_settings as ks

SEED = """
alembic_version: abc
zones:
- zone_id: "${uuid:zone_id:1}"
settings:
- {name: log_retention, category: logging, title: Log retention, value: '7', value_type: int, sanitize: 'False', services_restart: None, description: days}
- {name: https_insecure, category: logging, title: Insecure, value: 'True', value_type: bool, sanitize: 'False', services_restart: 'manager,api', description: x}
- {name: hec_token, category: logging, title: Token, value: 'None', value_type: password, sanitize: 'True', services_restart: None, description: x}
- {name: ratio, category: scale, title: Ratio, value: '0.5', value_type: float, sanitize: 'False', services_restart: None, description: x}
- {name: rules, category: web_filter, title: Rules, value: '{}', value_type: json, sanitize: 'False', services_restart: None, description: x}
- {name: banner, category: theme, title: Banner, value: 'hello', value_type: multiline_string, sanitize: 'False', services_restart: None, description: x}
"""


def test_the_catalogue_describes_each_setting_with_its_type_secrecy_and_restart_needs():
    by = {e["name"]: e for e in ks.catalogue(SEED)}
    assert by["log_retention"] == {"name": "log_retention", "category": "logging", "title": "Log retention", "type": "int", "default": "7", "secret": False, "restart": [], "description": "days"}
    assert by["https_insecure"]["restart"] == ["manager", "api"] and by["hec_token"]["secret"] is True


def test_overrides_change_only_what_was_asked_and_report_what_needs_a_restart():
    new, changes = ks.apply_overrides(SEED, {"log_retention": 14, "https_insecure": "false"})
    before, after = yaml.safe_load(SEED), yaml.safe_load(new)
    assert [c["name"] for c in changes] == ["log_retention", "https_insecure"]
    assert changes[1] == {"name": "https_insecure", "from": "True", "to": "False", "restart": ["manager", "api"]}
    assert [r["name"] for r, o in zip(after["settings"], before["settings"]) if r != o] == ["log_retention", "https_insecure"]
    assert after["zones"] == before["zones"] and after["alembic_version"] == "abc"
    assert re.findall(r"\$\{uuid:[a-z_:0-9]+\}", new) == re.findall(r"\$\{uuid:[a-z_:0-9]+\}", SEED)                  # template variables are untouched


def test_an_unknown_setting_is_refused_and_so_is_a_secret():
    with pytest.raises(ks.SettingsError, match="not a setting this Kasm release has"):
        ks.apply_overrides(SEED, {"nonsense": 1})
    with pytest.raises(ks.SettingsError, match="secret; it is generated"):
        ks.apply_overrides(SEED, {"hec_token": "abc"})


@pytest.mark.parametrize("name,value,why", [("log_retention", "many", "whole number"), ("https_insecure", "maybe", "true or false"), ("ratio", "x", "a number"), ("rules", "{bad", "JSON")])
def test_a_value_must_fit_its_type(name, value, why):
    with pytest.raises(ks.SettingsError, match=why):
        ks.apply_overrides(SEED, {name: value})


def test_values_are_normalised_the_way_kasm_stores_them():
    _, changes = ks.apply_overrides(SEED, {"https_insecure": "TRUE", "log_retention": " 21 ", "ratio": 1, "banner": "hi"})
    assert {c["name"]: c["to"] for c in changes} == {"https_insecure": "True", "log_retention": "21", "ratio": "1.0", "banner": "hi"}


def test_the_summary_is_a_report_not_a_table():
    report = ks.summary(ks.catalogue(SEED))
    assert report == {"settings": 6, "secrets": 1, "need_restart": 1, "categories": {"logging": 3, "scale": 1, "web_filter": 1, "theme": 1}}


def test_the_real_release_seed_round_trips_when_one_is_available():
    from pathlib import Path
    candidates = list(Path("/run/media/cane/CACHE/baseline-build/kasm").glob("**/default_properties.yaml")) + \
        list(Path("/tmp").glob("**/kasm_release/conf/database/seed_data/default_properties.yaml"))
    if not candidates:
        pytest.skip("no Kasm release seed on this machine")
    text = candidates[0].read_text()
    catalog = ks.catalogue(text)
    assert len(catalog) >= 80 and any(e["secret"] for e in catalog)
    new, _ = ks.apply_overrides(text, {catalog[0]["name"]: catalog[0]["default"]} if not catalog[0]["secret"] else {})
    assert yaml.safe_load(new) == yaml.safe_load(text)
