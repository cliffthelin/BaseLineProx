import pytest

import web_address as wa


def test_valid_address_and_port_are_written_once(tmp_path):
    f = tmp_path / "web.env"
    assert wa.save("10.0.0.5", 8100, path=f, local_addresses=["10.0.0.5"]) == {"bind_host": "10.0.0.5", "port": 8100}
    assert wa.read(f) == {"bind_host": "10.0.0.5", "port": 8100}
    m = f.stat().st_mtime_ns
    wa.save("10.0.0.5", 8100, path=f, local_addresses=["10.0.0.5"])
    assert f.stat().st_mtime_ns == m


@pytest.mark.parametrize("host,port", [("nope", 8100), ("10.0.0.5", 80), ("10.0.0.5", "8100"), ("10.0.0.5", True), ("10.0.0.9", 8100)])
def test_bad_values_are_refused(host, port, tmp_path):
    with pytest.raises(wa.AddressError):
        wa.save(host, port, path=tmp_path / "w", local_addresses=["10.0.0.5"])


def test_all_addresses_is_always_allowed(tmp_path):
    assert wa.save("0.0.0.0", 9000, path=tmp_path / "w", local_addresses=[])["bind_host"] == "0.0.0.0"


def test_missing_file_reads_as_the_default(tmp_path):
    assert wa.read(tmp_path / "none") == wa.DEFAULT
