import operations_page
import pytest
import remote_access


def test_remote_access_page_does_not_turn_failed_listener_probe_into_no_listeners():
    page = operations_page.render_remote_access_page({
        "ssh": {"active": None},
        "tailscale": {"ip": None, "peers": None},
        "listening": [],
        "listening_available": False,
        "observation_errors": ["ss -ltn: permission denied"],
        "warnings": [],
    }).decode()
    assert "Listener inventory unavailable" in page
    assert "ss -ltn: permission denied" in page
    assert "<li>none found</li>" not in page


@pytest.mark.parametrize("output", ["", "not an ss table\n", "State Recv-Q Send-Q\n"])
def test_listener_parser_rejects_output_that_cannot_prove_an_empty_inventory(output):
    with pytest.raises(remote_access.RemoteAccessObservationError, match="invalid ss output"):
        remote_access._parse_listening(output)


def test_listener_parser_accepts_valid_header_with_no_listeners():
    output = "State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
    assert remote_access._parse_listening(output) == []
