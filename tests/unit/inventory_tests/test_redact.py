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
