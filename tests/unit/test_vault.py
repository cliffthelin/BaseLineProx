"""The credential vault (operator, 2026-10-12): tokens and keys live in USER_ADMIN's vault (host/substrate) and USER_PERSONAL's (per user),
as private files, never in the code, never in a log line, never in an exception message. Real files under tmp_path."""
import os
import stat

import pytest

import vault as v

SECRET = "sk-ant-oat01-" + "Zx9" * 20


def test_a_secret_round_trips_in_a_private_file_inside_a_private_folder(tmp_path):
    vault = v.Vault(tmp_path / "vault")
    vault.put("CLAUDE_CODE_OAUTH_TOKEN", SECRET)
    assert vault.get("CLAUDE_CODE_OAUTH_TOKEN") == SECRET
    assert stat.S_IMODE((tmp_path / "vault").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "vault" / "CLAUDE_CODE_OAUTH_TOKEN").stat().st_mode) == 0o600
    assert vault.names() == ["CLAUDE_CODE_OAUTH_TOKEN"]
    assert not list((tmp_path / "vault").glob("*.tmp*"))                     # atomic write leaves nothing behind


def test_a_replaced_secret_is_replaced_whole_and_a_deleted_one_is_gone(tmp_path):
    vault = v.Vault(tmp_path)
    vault.put("OPENAI_API_KEY", "old-value-1234567890")
    vault.put("OPENAI_API_KEY", "new-value-0987654321")
    assert vault.get("OPENAI_API_KEY") == "new-value-0987654321"
    vault.delete("OPENAI_API_KEY")
    assert vault.get("OPENAI_API_KEY") is None and vault.names() == []


def test_build_roots_use_the_mounted_cache_ancestor_and_fall_back_to_partition_names(tmp_path, monkeypatch):
    import lane_files
    cache = tmp_path / "CACHE"
    build = cache / "baseline-build"
    build.mkdir(parents=True)
    monkeypatch.delenv("BASELINE_DRIVES_FILE", raising=False)
    monkeypatch.setattr(lane_files, "BUILD_DRIVES_FILE", str(build / "drives.json"))
    monkeypatch.setattr(os.path, "ismount", lambda path: str(path) == str(cache))
    assert v.build_aware_roots() == (str(build / "parent-user-admin/vault"), str(build / "parent-user-personal/vault"))

    monkeypatch.setattr(os.path, "ismount", lambda _path: False)
    assert v.build_aware_roots() == (v.ADMIN_VAULT, v.PERSONAL_VAULT)
    assert "/run/media/cane/CACHE" not in open(v.__file__).read()


@pytest.mark.parametrize("bad", ["", "lower", "A", "../ETC", "A/B", "A B", "X" * 80, "1ABC"])
def test_only_plain_upper_case_names_are_accepted(tmp_path, bad):
    with pytest.raises(v.VaultError):
        v.Vault(tmp_path).put(bad, "value-1234567890")


def test_values_that_cannot_be_one_line_secrets_are_refused_without_echoing_them(tmp_path):
    vault = v.Vault(tmp_path)
    for bad in ("", "short", "two\nlines-1234567890", "nul\x00byte-1234567890"):
        with pytest.raises(v.VaultError) as raised:
            vault.put("OPENAI_API_KEY", bad)
        assert bad.strip() == "" or bad not in str(raised.value)


def test_a_symlink_in_the_vault_is_never_followed(tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text("not-a-secret-at-all-1234")
    root = tmp_path / "vault"
    root.mkdir(mode=0o700)
    os.symlink(target, root / "OPENAI_API_KEY")
    vault = v.Vault(root)
    with pytest.raises(v.VaultError):
        vault.get("OPENAI_API_KEY")
    with pytest.raises(v.VaultError):
        vault.put("OPENAI_API_KEY", "replacement-1234567890")
    assert target.read_text() == "not-a-secret-at-all-1234"


def test_a_vault_folder_that_others_can_read_is_refused(tmp_path):
    root = tmp_path / "vault"
    root.mkdir(mode=0o755)
    with pytest.raises(v.VaultError):
        v.Vault(root).put("OPENAI_API_KEY", "value-1234567890")


def test_status_never_contains_a_value_only_names_and_a_short_fingerprint(tmp_path):
    vault = v.Vault(tmp_path)
    vault.put("CLAUDE_CODE_OAUTH_TOKEN", SECRET)
    status = vault.status()
    assert SECRET not in repr(status)
    assert status[0]["name"] == "CLAUDE_CODE_OAUTH_TOKEN" and len(status[0]["fingerprint"]) == 8 and status[0]["length"] == len(SECRET)


def test_the_lookup_order_is_process_environment_then_personal_then_admin(tmp_path):
    admin, personal = v.Vault(tmp_path / "a"), v.Vault(tmp_path / "p")
    admin.put("OPENAI_API_KEY", "from-admin-vault-0001")
    assert v.lookup("OPENAI_API_KEY", vaults=[personal, admin], environ={}) == "from-admin-vault-0001"
    personal.put("OPENAI_API_KEY", "from-personal-vault-02")
    assert v.lookup("OPENAI_API_KEY", vaults=[personal, admin], environ={}) == "from-personal-vault-02"
    assert v.lookup("OPENAI_API_KEY", vaults=[personal, admin], environ={"OPENAI_API_KEY": "from-env-value-0003"}) == "from-env-value-0003"
    assert v.lookup("GEMINI_API_KEY", vaults=[personal, admin], environ={}) is None
