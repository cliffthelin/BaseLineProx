"""Vault encryption at rest: passphrase-sealed secrets (AES-256-CTR via openssl + scrypt-derived HMAC-SHA256, encrypt-then-MAC), a
verifier so a wrong passphrase is told apart from tampering, and an unlock that places plaintext only on a RAM-backed runtime folder."""
import os
import stat

import pytest

import vault as v
import vault_crypto as vc

PASS = "correct horse battery staple 41"
SECRET = "sk-ant-oat01-" + "Hk3" * 25


def test_a_sealed_value_round_trips_and_reveals_nothing_on_disk_form():
    token = vc.seal(SECRET, PASS)
    assert token.startswith("ENC1:") and SECRET not in token and "sk-ant" not in token
    assert vc.open_sealed(token, PASS) == SECRET


def test_the_same_secret_seals_differently_each_time():
    assert vc.seal(SECRET, PASS) != vc.seal(SECRET, PASS)


def test_a_wrong_passphrase_and_a_modified_token_are_both_refused_and_say_which():
    token = vc.seal(SECRET, PASS)
    with pytest.raises(vc.WrongPassphrase):
        vc.open_sealed(token, "not the passphrase 123456")
    body = token[len("ENC1:"):]
    tampered = "ENC1:" + body[:-4] + ("AAAA" if not body.endswith("AAAA") else "BBBB")
    with pytest.raises(vc.WrongPassphrase):                  # an altered token fails the MAC; it is never decrypted
        vc.open_sealed(tampered, PASS)
    with pytest.raises(vc.SealError):
        vc.open_sealed("plain-text-not-a-token", PASS)


def test_the_passphrase_is_never_on_a_command_line(monkeypatch):
    seen = []
    import subprocess
    real = subprocess.run

    def spy(argv, *a, **k):
        seen.append(list(argv))
        return real(argv, *a, **k)

    monkeypatch.setattr(vc.subprocess, "run", spy)
    vc.open_sealed(vc.seal(SECRET, PASS), PASS)
    assert seen and all(PASS not in " ".join(a) and SECRET not in " ".join(a) for a in seen)


def test_short_passphrases_are_refused():
    with pytest.raises(vc.SealError):
        vc.seal(SECRET, "short")


def test_an_encrypted_vault_stores_only_ciphertext_and_needs_the_passphrase_to_read(tmp_path):
    vault = v.Vault(tmp_path / "vault")
    vault.set_passphrase(PASS)
    vault.put("OPENAI_API_KEY", SECRET, passphrase=PASS)
    raw = (tmp_path / "vault" / "OPENAI_API_KEY").read_text()
    assert raw.startswith("ENC1:") and SECRET not in raw
    with pytest.raises(v.VaultLocked):
        vault.get("OPENAI_API_KEY")
    assert vault.get("OPENAI_API_KEY", passphrase=PASS) == SECRET
    assert vault.status()[0]["locked"] is True and SECRET not in repr(vault.status())


def test_the_verifier_tells_a_wrong_passphrase_without_touching_a_secret(tmp_path):
    vault = v.Vault(tmp_path / "vault")
    vault.set_passphrase(PASS)
    assert vault.check_passphrase(PASS) is True and vault.check_passphrase("wrong passphrase 12345") is False
    with pytest.raises(v.VaultError):
        vault.set_passphrase("another passphrase 99999")      # an existing vault passphrase is changed, never silently replaced


def test_setting_a_passphrase_seals_the_secrets_already_stored_in_plain(tmp_path):
    vault = v.Vault(tmp_path / "vault")
    vault.put("GEMINI_API_KEY", "gemini-plain-value-0001")
    vault.set_passphrase(PASS)
    assert (tmp_path / "vault" / "GEMINI_API_KEY").read_text().startswith("ENC1:")
    assert vault.get("GEMINI_API_KEY", passphrase=PASS) == "gemini-plain-value-0001"


def test_unlock_places_plaintext_only_in_the_runtime_folder_and_lock_removes_it(tmp_path):
    vault = v.Vault(tmp_path / "vault")
    vault.set_passphrase(PASS)
    vault.put("OPENAI_API_KEY", SECRET, passphrase=PASS)
    run = tmp_path / "run"
    assert vault.unlock(PASS, run) == ["OPENAI_API_KEY"]
    assert stat.S_IMODE(run.stat().st_mode) == 0o700 and stat.S_IMODE((run / "OPENAI_API_KEY").stat().st_mode) == 0o600
    assert v.lookup("OPENAI_API_KEY", vaults=[vault], environ={}, runtime=run) == SECRET
    vault.lock(run)
    assert not (run / "OPENAI_API_KEY").exists()
    assert v.lookup("OPENAI_API_KEY", vaults=[vault], environ={}, runtime=run) is None
    with pytest.raises(v.WrongPassphrase if hasattr(v, "WrongPassphrase") else v.VaultError):
        vault.unlock("wrong passphrase 12345", run)
