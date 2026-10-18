"""How Baseline's settings are shown: a card per topic, a row per setting with a plain name and a sentence about it, and the right control for what it is.

A switch for on/off, a segmented control for a short list of choices, a drop-down for a longer list, and a typed field only where the value is free text. The raw setting name stays visible in
Advanced mode, so nothing is hidden or renamed in the data: the forms post the same field names the stored settings use, with the same hidden type hints, so saving works exactly as before.
A setting this file has no words for is still shown (with a name made from its key), never left out.
"""
from __future__ import annotations

import html

# section -> (title, one sentence, simple-mode title)
SECTIONS = {
    "network": ("Network", "How this computer is named and addressed on your network.", "Network"),
    "firewall": ("Firewall", "Who may connect to this computer.", "Firewall"),
    "tether": ("Phone tethering", "Use a phone's internet connection over USB.", "Phone internet"),
    "ssh": ("Remote sign-in", "Signing in to this computer from another one (SSH).", "Remote sign-in"),
    "handoff": ("Handoff", "Restoring settings from an earlier backup.", "Restore from backup"),
    "drivers": ("Drivers and firmware", "Updates that keep your hardware working properly.", "Drivers"),
    "proxmox": ("Drive health", "Watches your drives and warns you before one fails.", "Drive health"),
    "diagnostics": ("Diagnostic tool definitions", "How each checkup tool is installed and what it asks for.", "Checkups"),
    "ethtool": ("Network adapter tuning", "Low-level settings for a network card. The defaults are right for almost everyone.", "Network adapter"),
}
# key -> (plain label, one sentence)
LABELS = {
    "hostname": ("Computer name", "How this computer shows up on your network."),
    "dhcp": ("Get an address automatically", "Recommended. Turn off only if your network needs a fixed address."),
    "allow_lan_only": ("Only allow connections from my home network", "Blocks everything from outside your local network."),
    "enabled": ("Allow phone tethering", "Lets Baseline use a phone plugged in by USB as a backup internet connection."),
    "password_auth": ("Allow signing in with a password", "Off means only people with a key can sign in, which is safer."),
    "restored_categories": ("What to restore", "The kinds of settings brought back from a backup."),
    "archive_path": ("Backup file", "Where the backup to restore from is."),
    "cpu_microcode": ("Keep processor fixes up to date", "Installs the processor maker's own fixes for bugs and security problems."),
    "cpu_microcode_package": ("Processor maker", "Which maker's fixes to use."),
    "nic_wifi_firmware": ("Keep wireless card firmware up to date", "Installs the firmware your wireless card needs."),
    "wifi_firmware_package": ("Wireless card maker", "Which maker's firmware to use."),
    "smartd_health_check": ("Watch drive health", "Checks your drives regularly and logs problems."),
    "smartd_monitor_all": ("Watch every drive", "Include all drives, not just the ones already known."),
    "smartd_auto_offline": ("Run background drive checks", "Lets drives check themselves while idle."),
    "smartd_attribute_autosave": ("Remember drive readings", "Keeps drive readings between restarts so trends show."),
    "smartd_selftest_schedule": ("Scheduled drive tests", "How often drives run a full self-test."),
    "smartd_email": ("Email me about drive problems", "Leave empty for no email."),
    "smartd_email_frequency": ("How often to remind me", "While a problem remains."),
    "ethtool_interface": ("Network card to adjust", "Which card these settings apply to."),
    "ethtool_autoneg": ("Speed and duplex", "Automatic works for nearly every network."),
    "ethtool_speed": ("Link speed", "Leave unchanged unless a cable or switch needs a fixed speed."),
    "ethtool_duplex": ("Duplex", "Full duplex is normal."),
    "ethtool_wol": ("Wake on LAN", "Which network signal may turn this computer on."),
    "ethtool_rx_checksum": ("Receive checksum offload", "Lets the card check incoming data."),
    "ethtool_tx_checksum": ("Send checksum offload", "Lets the card check outgoing data."),
    "ethtool_tso": ("TCP segmentation offload", "Lets the card split large sends."),
    "ethtool_gro": ("Generic receive offload", "Lets the system combine incoming data."),
    "ethtool_pause_autoneg": ("Flow control", "Let the card slow the sender when it is overloaded."),
}
SEG_MAX = 3
SEG_LABEL_MAX = 16                 # a segmented control only for short choices; longer wording reads better in a drop-down
NESTED_ADVANCED = ("diagnostics",)
ADVANCED_ONLY = ("handoff",)          # cards for list-valued data: shown in Advanced only   # tool definitions: nested data, advanced only and folded


def humanize(key: str) -> str:
    words = key.replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def row(key: str, control: str, *, label=None, help_text=None) -> str:
    plain, sentence = LABELS.get(key, (humanize(key), ""))
    e = html.escape
    wide = " wide" if "data-structured-editor" in control else ""
    return (f'<div class="setting{wide}"><div class="setting-text"><b>{e(label or plain)}</b>'
            f'{f"<span>{e(help_text or sentence)}</span>" if (help_text or sentence) else ""}<code class="adv">{e(key)}</code></div>'
            f'<div class="setting-control">{control}</div></div>')


def switch(key: str, value: bool) -> str:
    e = html.escape(key, quote=True)
    return (f'<input type="hidden" name="{e}__type" value="bool"><label class="switch"><input type="checkbox" name="{e}" value="true" {"checked" if value else ""}><i></i>'
            f'<span class="sr">{html.escape(LABELS.get(key, (humanize(key),))[0])}</span></label>')


def segmented(key: str, value, choices: list, type_name: str) -> str:
    e = html.escape(key, quote=True)
    items = "".join(f'<input type="radio" name="{e}" id="{e}-{i}" value="{html.escape(str(v), quote=True)}" {"checked" if str(v) == str(value) else ""}>'
                    f'<label for="{e}-{i}">{html.escape(label)}</label>' for i, (v, label) in enumerate(choices))
    return f'<input type="hidden" name="{e}__type" value="{type_name}"><div class="seg" role="radiogroup">{items}</div>'


def control_for(key: str, value, *, options=None, render_field_input, field_choices) -> str:
    if isinstance(value, bool):
        return switch(key, value)
    choices = field_choices.get(key) if options is None else None
    if choices is not None and len(choices) <= SEG_MAX and max(len(label) for _, label in choices) <= SEG_LABEL_MAX and any(str(v) == str(value) for v, _ in choices):
        return segmented(key, value, choices, "str" if isinstance(value, str) else "json")
    return render_field_input(key, value, options=options)


def render_sections(settings: dict, *, render_field_input, field_choices, interface_choices=None) -> str:
    """The cards for every (non-private) section. A section that mixes topics (proxmox: drive health and network adapter) is split into one card per topic."""
    cards = []
    for section, values in settings.items():
        if section.startswith("_") or not isinstance(values, dict):
            continue
        if section in NESTED_ADVANCED:
            title, sentence, _ = SECTIONS.get(section, (humanize(section), "", humanize(section)))
            rows = "".join(row(k, render_field_input(k, v)) for k, v in values.items())
            cards.append(f'<section class="card settings-card adv"><details><summary><h2 style="display:inline">{html.escape(title)}</h2> <span class="dim">(advanced)</span></summary>'
                         f'<form method="post" action="/settings/{html.escape(section, quote=True)}" data-autosave>{rows}<span role="status" data-save-status aria-live="polite"></span></form></details></section>')
            continue
        parts = {}
        for key, value in values.items():
            parts.setdefault("ethtool" if key.startswith("ethtool_") else section, {})[key] = value
        for name, group in parts.items():
            title, sentence, simple = SECTIONS.get(name, (humanize(name), "", humanize(name)))
            rows = "".join(row(k, control_for(k, v, options=interface_choices if k == "ethtool_interface" else None,
                                              render_field_input=render_field_input, field_choices=field_choices)) for k, v in group.items())
            cards.append(f'<section class="card settings-card{" adv" if section in ADVANCED_ONLY else ""}"><h2><span class="m-adv">{html.escape(title)}</span><span class="m-simple">{html.escape(simple)}</span></h2>'
                         f'{f"<p class=dim>{html.escape(sentence)}</p>" if sentence else ""}'
                         f'<form method="post" action="/settings/{html.escape(section, quote=True)}" data-autosave>{rows}'
                         f'<span role="status" data-save-status aria-live="polite"></span></form></section>')
    return f'<div class="settings-stack">{"".join(cards)}</div>'
