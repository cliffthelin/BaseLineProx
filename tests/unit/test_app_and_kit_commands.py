"""The two command-line helpers: what they print and refuse. The kit one is shown against a fake registry."""
import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

BIN = Path(__file__).parents[2] / "baseline" / "bin"


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(BIN / name))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def test_the_app_helper_lists_shows_the_route_and_script_and_refuses_the_unknown(capsys):
    app = load("baseline-app-install")
    assert app.main(["list", "--category", "browsers"]) == 0 and "firefox" in capsys.readouterr().out
    assert app.main(["show", "firefox", "--os", "debian"]) == 0
    out = capsys.readouterr().out
    assert "route apt" in out and "apt-get install -y firefox-esr" in out
    assert app.main(["show", "firefox", "--os", "nixos"]) == 0 and "declared in the configuration" in capsys.readouterr().out
    assert app.main(["show", "notanapp", "--os", "debian"]) == 2
    assert app.main(["show", "firefox", "--os", "windows"]) == 1 and "not a system" in capsys.readouterr().err


def test_running_an_install_needs_root_and_prints_the_script_first(capsys, monkeypatch):
    app = load("baseline-app-install")
    monkeypatch.setattr(app.os, "geteuid", lambda: 1000)
    assert app.main(["run", "firefox", "--os", "debian"]) == 1
    captured = capsys.readouterr()
    assert "apt-get install -y firefox-esr" in captured.out and "needs root" in captured.err


def test_the_kit_helper_prints_the_digest_to_review_and_what_the_kit_does(capsys, monkeypatch):
    import sbx_kits
    from test_sbx_kits import SPEC, hub
    opener, manifest_digest, _ = hub()
    kits = load("baseline-sbx-kits")
    real = sbx_kits.Registry
    monkeypatch.setattr(sbx_kits, "Registry", lambda *a, **k: real(opener))
    assert kits.main(["review", "registry.example/sbx/task-kit:latest"]) == 0
    out = capsys.readouterr().out
    assert sbx_kits.short(manifest_digest) in out and "install:runs-as-root" in out and SPEC.splitlines()[0] in out
    assert kits.main(["review"]) == 2
