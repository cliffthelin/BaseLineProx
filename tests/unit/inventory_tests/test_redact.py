from inventory.redact import Redactor


def test_stable_within_one_run():
    r = Redactor(key=b"fixed-key")
    a = r.tokenize("10.0.0.5", "ip")
    b = r.tokenize("10.0.0.5", "ip")
    assert a == b


def test_different_keys_produce_different_tokens_across_runs():
    r1 = Redactor(key=b"key-one")
    r2 = Redactor(key=b"key-two")
    assert r1.tokenize("10.0.0.5", "ip") != r2.tokenize("10.0.0.5", "ip")


def test_different_values_produce_different_tokens():
    r = Redactor(key=b"fixed-key")
    assert r.tokenize("10.0.0.5", "ip") != r.tokenize("10.0.0.6", "ip")


def test_default_key_is_random_each_instance():
    r1 = Redactor()
    r2 = Redactor()
    assert r1.tokenize("10.0.0.5", "ip") != r2.tokenize("10.0.0.5", "ip")


def test_token_never_contains_the_raw_value():
    r = Redactor(key=b"fixed-key")
    token = r.tokenize("10.0.0.5", "ip")
    assert "10.0.0.5" not in token


def test_none_passes_through_as_none():
    r = Redactor(key=b"fixed-key")
    assert r.tokenize(None, "ip") is None


def test_fields_redacted_counts_unique_tokenized_values():
    r = Redactor(key=b"fixed-key")
    r.tokenize("10.0.0.5", "ip")
    r.tokenize("10.0.0.5", "ip")  # same value again - not a new field
    r.tokenize("10.0.0.6", "ip")
    assert r.fields_redacted == 2


def test_key_id_is_stable_for_the_same_key():
    r1 = Redactor(key=b"same-key")
    r2 = Redactor(key=b"same-key")
    assert r1.key_id == r2.key_id


def test_key_id_differs_for_different_keys():
    r1 = Redactor(key=b"key-one")
    r2 = Redactor(key=b"key-two")
    assert r1.key_id != r2.key_id


def test_key_id_never_contains_the_raw_key():
    r = Redactor(key=b"a-fairly-long-comparison-key-value")
    assert b"a-fairly-long-comparison-key-value" not in r.key_id.encode()


def test_key_id_is_independent_of_tokenize_digest():
    """key_id (SHA-256 of the raw key) must not be derivable from, or
    reused as, any per-value HMAC token - the two answer different
    questions and must use unrelated hash inputs."""
    r = Redactor(key=b"fixed-key")
    token = r.tokenize("10.0.0.5", "ip")
    assert r.key_id not in token
    assert token.split(":", 1)[1] not in r.key_id
