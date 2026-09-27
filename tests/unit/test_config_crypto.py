"""Unit tests for config_crypto.py - real password-based encryption of
the whole exported Master Config file, or specific targeted fields
within it. No real openssl is ever invoked - the FakeRunner records
every argv and simulates file contents in memory.

Direct instruction covered: "there should be the option to encrypt and
password protect the Master Config file or targeted fields or pages."
"""
from fake_runner import FakeProc, FakeRunner

import config_crypto as cc


def test_encrypt_file_argv_is_real_openssl_aes256_pbkdf2():
    argv = cc.encrypt_file_argv("/tmp/in.json", "/tmp/out.enc", "/tmp/pass")
    assert argv == ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-a",
                     "-pass", "file:/tmp/pass", "-in", "/tmp/in.json", "-out", "/tmp/out.enc"]


def test_decrypt_file_argv_is_the_real_reverse():
    argv = cc.decrypt_file_argv("/tmp/in.enc", "/tmp/out.json", "/tmp/pass")
    assert argv == ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-a",
                     "-pass", "file:/tmp/pass", "-in", "/tmp/in.enc", "-out", "/tmp/out.json"]


def test_encrypt_file_reports_success():
    runner = FakeRunner()
    result = cc.encrypt_file(runner, in_path="/tmp/in.json", out_path="/tmp/out.enc", password_file="/tmp/pass")
    assert result.ok is True


def test_encrypt_file_reports_a_real_failure():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["openssl", "enc"] and "-d" not in a, FakeProc(1, "", "bad password")),
    ])
    result = cc.encrypt_file(runner, in_path="/tmp/in.json", out_path="/tmp/out.enc", password_file="/tmp/pass")
    assert result.ok is False
    assert "bad password" in result.detail


def test_decrypt_file_reports_a_real_failure():
    runner = FakeRunner(command_responses=[
        (lambda a: "-d" in a, FakeProc(1, "", "bad decrypt")),
    ])
    result = cc.decrypt_file(runner, in_path="/tmp/in.enc", out_path="/tmp/out.json", password_file="/tmp/pass")
    assert result.ok is False
    assert "bad decrypt" in result.detail


# -- get/set dotted paths in a nested config dict --------------------------

def test_get_dotted_path():
    config = {"credentials": {"root_password": "s3cret"}}
    assert cc.get_dotted(config, "credentials.root_password") == "s3cret"


def test_set_dotted_path():
    config = {"credentials": {"root_password": "s3cret"}}
    cc.set_dotted(config, "credentials.root_password", "REPLACED")
    assert config["credentials"]["root_password"] == "REPLACED"


# -- targeted-field encryption/decryption -----------------------------------

def test_encrypt_json_fields_replaces_only_the_named_fields():
    runner = FakeRunner()

    def fake_run(argv, timeout=10):
        if argv[:2] == ["openssl", "enc"] and "-d" not in argv:
            out_path = argv[argv.index("-out") + 1]
            runner.files[out_path] = "U2FsdGVkX1+fakeCiphertext=="
        return FakeProc(0, "", "")
    runner.run = fake_run

    config = {"credentials": {"root_password": "s3cret", "note": "not sensitive"}}
    result = cc.encrypt_json_fields(runner, config, ["credentials.root_password"], password_file="/tmp/pass")

    assert result["credentials"]["note"] == "not sensitive"  # untouched
    encrypted = result["credentials"]["root_password"]
    assert encrypted["__encrypted__"] is True
    assert encrypted["cipher"] == "aes-256-cbc-pbkdf2"
    assert encrypted["data"] == "U2FsdGVkX1+fakeCiphertext=="


def test_encrypt_json_fields_cleans_up_its_temp_files():
    runner = FakeRunner()
    calls = []

    def fake_run(argv, timeout=10):
        if argv[:2] == ["openssl", "enc"]:
            out_path = argv[argv.index("-out") + 1]
            runner.files[out_path] = "ciphertext"
        return FakeProc(0, "", "")
    runner.run = fake_run

    config = {"credentials": {"root_password": "s3cret"}}
    cc.encrypt_json_fields(runner, config, ["credentials.root_password"], password_file="/tmp/pass")
    assert runner.files == {}  # both the plaintext temp-in and ciphertext temp-out were removed


def test_decrypt_json_fields_restores_the_named_fields():
    runner = FakeRunner()

    def fake_run(argv, timeout=10):
        if "-d" in argv:
            out_path = argv[argv.index("-out") + 1]
            runner.files[out_path] = "s3cret"
        return FakeProc(0, "", "")
    runner.run = fake_run

    config = {"credentials": {"root_password": {
        "__encrypted__": True, "cipher": "aes-256-cbc-pbkdf2", "data": "U2FsdGVkX1+fake=="}}}
    result = cc.decrypt_json_fields(runner, config, password_file="/tmp/pass")
    assert result["credentials"]["root_password"] == "s3cret"


def test_decrypt_json_fields_writes_the_ciphertext_with_a_trailing_newline():
    """Real bug found on a live smoke test against real openssl:
    writing the base64 ciphertext WITHOUT a trailing newline makes
    openssl's own base64 decoder fail with "error reading input file"
    - not even a wrong-password error, an earlier parse failure. This
    is a real openssl quirk no FakeRunner can catch on its own, so the
    fix is asserted directly against what gets written, independent of
    whether the rest of the (unconfigured) run() call succeeds."""
    runner = FakeRunner()
    config = {"credentials": {"root_password": {
        "__encrypted__": True, "cipher": "aes-256-cbc-pbkdf2", "data": "U2FsdGVkX1+fake=="}}}
    try:
        cc.decrypt_json_fields(runner, config, password_file="/tmp/pass")
    except FileNotFoundError:
        pass  # the fake's default run() doesn't populate tmp_out - irrelevant to this assertion
    written = next(v for k, v in runner.files.items() if v.rstrip("\n") == "U2FsdGVkX1+fake==")
    assert written.endswith("\n")


def test_decrypt_json_fields_leaves_plain_fields_alone():
    runner = FakeRunner()
    config = {"credentials": {"note": "not sensitive"}}
    result = cc.decrypt_json_fields(runner, config, password_file="/tmp/pass")
    assert result == config
    assert runner.calls == []  # no real openssl invocation for a config with nothing encrypted


def test_decrypt_json_fields_reports_a_wrong_password_without_corrupting_the_field():
    runner = FakeRunner(command_responses=[
        (lambda a: "-d" in a, FakeProc(1, "", "bad decrypt")),
    ])
    config = {"credentials": {"root_password": {
        "__encrypted__": True, "cipher": "aes-256-cbc-pbkdf2", "data": "U2FsdGVkX1+fake=="}}}
    result, errors = cc.decrypt_json_fields(runner, config, password_file="/tmp/pass", return_errors=True)
    assert errors == ["credentials.root_password"]
    # the field stays in its encrypted form - never silently corrupted/blanked on failure
    assert result["credentials"]["root_password"]["__encrypted__"] is True


def test_find_encrypted_field_paths():
    config = {"a": {"b": {"__encrypted__": True, "cipher": "x", "data": "y"}, "c": "plain"}}
    assert cc.find_encrypted_field_paths(config) == ["a.b"]
