"""tools/vault-import: the OPERATOR runs it on a file of their own credentials; the agent never reads the file or the values."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path

import pytest

import vault as v

TOOL = Path(__file__).resolve().parents[2] / "tools" / "vault-import"


def load():
    loader = importlib.machinery.SourceFileLoader("vault_import", str(TOOL))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("vault_import", loader))
    loader.exec_module(module)
    return module


def test_only_known_provider_names_are_imported_and_nothing_else_is_kept(tmp_path):
    tool = load()
    source = tmp_path / "creds.env"
    source.write_text("# comment\nOPENAI_API_KEY=sk-openai-value-000001\nexport GEMINI_API_KEY='gemini-value-00000002'\n"
                      "AWS_SECRET_ACCESS_KEY=must-not-be-imported-0001\nbroken line\nCLAUDE_CODE_OAUTH_TOKEN=\"sk-ant-oat01-aaaaaaaaaaaaaaaaaaaa\"\n")
    os.chmod(source, 0o600)
    vault = v.Vault(tmp_path / "vault")
    report = tool.import_file(source, vault, passphrase=None)
    assert sorted(report["imported"]) == ["CLAUDE_CODE_OAUTH_TOKEN", "GEMINI_API_KEY", "OPENAI_API_KEY"]
    assert report["skipped"] == ["AWS_SECRET_ACCESS_KEY"] and vault.get("OPENAI_API_KEY") == "sk-openai-value-000001"
    assert "sk-openai" not in repr(report)


def test_a_source_file_others_can_read_is_refused(tmp_path):
    tool = load()
    source = tmp_path / "creds.env"
    source.write_text("OPENAI_API_KEY=sk-openai-value-000001\n")
    os.chmod(source, 0o644)
    with pytest.raises(SystemExit):
        tool.import_file(source, v.Vault(tmp_path / "vault"), passphrase=None)


def test_a_sealed_vault_is_filled_sealed(tmp_path):
    tool = load()
    vault = v.Vault(tmp_path / "vault")
    vault.set_passphrase("a vault passphrase 2026")
    source = tmp_path / "creds.env"
    source.write_text("OPENAI_API_KEY=sk-openai-value-000001\n")
    os.chmod(source, 0o600)
    tool.import_file(source, vault, passphrase="a vault passphrase 2026")
    assert (tmp_path / "vault" / "OPENAI_API_KEY").read_text().startswith("ENC1:")
