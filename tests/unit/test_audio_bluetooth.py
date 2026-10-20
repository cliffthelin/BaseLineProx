"""Audio and Bluetooth devices for the host's browser session, shown and controlled from the web app. Parsers are fed the tools' real output
shapes; every command is an exact argument list with a validated device address."""
import pytest

import audio_bluetooth as ab

BT_DEVICES = """Device AA:BB:CC:DD:EE:01 WH-1000XM5
Device 11:22:33:44:55:66 Keyboard K380
"""
BT_INFO = """Device AA:BB:CC:DD:EE:01 (public)
\tName: WH-1000XM5
\tPaired: yes
\tTrusted: yes
\tConnected: yes
"""
PACTL_SINKS = "49\talsa_output.pci-0000_00_1f.3.analog-stereo\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n" \
              "76\tbluez_output.AA_BB_CC_DD_EE_01.1\tPipeWire\ts16le 2ch 44100Hz\tRUNNING\n"
PACTL_SOURCES = "50\talsa_input.pci-0000_00_1f.3.analog-stereo\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n" \
                "51\talsa_output.pci-0000_00_1f.3.analog-stereo.monitor\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"


def test_bluetooth_devices_are_parsed_with_their_state():
    devices = ab.parse_bt_devices(BT_DEVICES)
    assert devices == [{"mac": "AA:BB:CC:DD:EE:01", "name": "WH-1000XM5"}, {"mac": "11:22:33:44:55:66", "name": "Keyboard K380"}]
    info = ab.parse_bt_info(BT_INFO)
    assert info == {"paired": True, "trusted": True, "connected": True}


def test_audio_outputs_and_inputs_are_listed_without_the_monitor_pseudo_inputs():
    sinks = ab.parse_pactl_short(PACTL_SINKS)
    sources = [s for s in ab.parse_pactl_short(PACTL_SOURCES) if not s["name"].endswith(".monitor")]
    assert [s["name"] for s in sinks][1].startswith("bluez_output") and sinks[1]["state"] == "RUNNING"
    assert [s["name"] for s in sources] == ["alsa_input.pci-0000_00_1f.3.analog-stereo"]


@pytest.mark.parametrize("action", ["connect", "disconnect", "pair", "trust", "remove"])
def test_each_action_is_one_exact_bluetoothctl_call_with_the_address(action):
    assert ab.action_argv(action, "aa:bb:cc:dd:ee:01") == ["bluetoothctl", action, "AA:BB:CC:DD:EE:01"]


@pytest.mark.parametrize("bad", ["", "AA:BB", "AA:BB:CC:DD:EE:0G", "AA:BB:CC:DD:EE:01; reboot", "../etc"])
def test_a_device_address_must_be_a_plain_mac(bad):
    with pytest.raises(ValueError):
        ab.action_argv("connect", bad)


def test_an_unknown_action_is_refused():
    with pytest.raises(ValueError):
        ab.action_argv("power-off-host", "AA:BB:CC:DD:EE:01")


def test_the_page_names_missing_tools_instead_of_showing_an_empty_list():
    html = ab.render({"sinks": None, "sources": None, "bluetooth": None, "tools": {"pactl": False, "bluetoothctl": False}}).decode()
    assert "not installed yet" in html.lower() and "installs the sound and bluetooth packages itself" in html.lower()
