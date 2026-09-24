"""Realistic Proxmox/Debian fixtures for both APT source formats -
legacy .list and Deb822 .sources - covering exactly the drift this
module exists to catch: a rebuilt host silently updating from the
wrong channel."""
from inventory.collectors import apt_sources
from inventory.runner import CommandResult

from .fake_runner import FakeRunner

DEBIAN_TRIXIE_LIST = """\
deb http://deb.debian.org/debian trixie main contrib non-free-firmware
deb http://deb.debian.org/debian trixie-updates main contrib non-free-firmware
deb http://security.debian.org/debian-security trixie-security main contrib non-free-firmware
"""

PROXMOX_NO_SUBSCRIPTION_LIST = """\
# Proxmox VE No-Subscription Repository
deb [arch=amd64 signed-by=/usr/share/keyrings/proxmox-archive-keyring.gpg] http://download.proxmox.com/debian/pve trixie pve-no-subscription
"""

PROXMOX_ENTERPRISE_SOURCES_DISABLED = """\
Types: deb
URIs: https://enterprise.proxmox.com/debian/pve
Suites: trixie
Components: pve-enterprise
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
Enabled: no
"""

DEBIAN_DEB822_SOURCES = """\
Types: deb deb-src
URIs: http://deb.debian.org/debian
Suites: trixie trixie-updates
Components: main contrib non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
Architectures: amd64
"""


def test_legacy_list_parses_debian_suites_and_components():
    entries = apt_sources.parse_list_text(DEBIAN_TRIXIE_LIST, "/etc/apt/sources.list")
    assert len(entries) == 3
    first = entries[0]
    assert first["format"] == "list"
    assert first["type"] == "deb"
    assert first["enabled"] is True
    assert first["uri"] == "http://deb.debian.org/debian"
    assert first["suites"] == ["trixie"]
    assert set(first["components"]) == {"main", "contrib", "non-free-firmware"}
    assert first["channel"] == "distro"


def test_legacy_list_parses_inline_arch_and_signed_by_options():
    entries = apt_sources.parse_list_text(PROXMOX_NO_SUBSCRIPTION_LIST, "/etc/apt/sources.list.d/pve.list")
    assert len(entries) == 1
    e = entries[0]
    assert e["architectures"] == ["amd64"]
    assert e["signed_by"] == "/usr/share/keyrings/proxmox-archive-keyring.gpg"
    assert e["channel"] == "no-subscription"
    assert e["enabled"] is True


def test_legacy_list_commented_line_is_disabled_not_dropped():
    text = "# " + PROXMOX_NO_SUBSCRIPTION_LIST.splitlines()[1]
    entries = apt_sources.parse_list_text(text, "/etc/apt/sources.list.d/pve.list")
    assert len(entries) == 1
    assert entries[0]["enabled"] is False


def test_deb822_parses_multiple_types_and_uris_as_separate_entries():
    entries = apt_sources.parse_deb822_text(DEBIAN_DEB822_SOURCES, "/etc/apt/sources.list.d/debian.sources")
    # 2 types (deb, deb-src) x 1 URI = 2 entries
    assert len(entries) == 2
    kinds = {e["type"] for e in entries}
    assert kinds == {"deb", "deb-src"}
    for e in entries:
        assert e["format"] == "deb822"
        assert e["suites"] == ["trixie", "trixie-updates"]
        assert set(e["components"]) == {"main", "contrib", "non-free-firmware"}
        assert e["architectures"] == ["amd64"]
        assert e["enabled"] is True


def test_deb822_enabled_no_is_respected():
    entries = apt_sources.parse_deb822_text(PROXMOX_ENTERPRISE_SOURCES_DISABLED,
                                             "/etc/apt/sources.list.d/pve-enterprise.sources")
    assert len(entries) == 1
    assert entries[0]["enabled"] is False
    assert entries[0]["channel"] == "enterprise"


def test_deb822_missing_blank_line_separator_still_parses_single_stanza():
    # No trailing blank line - flush() must still fire at EOF.
    text = DEBIAN_DEB822_SOURCES.rstrip("\n")
    entries = apt_sources.parse_deb822_text(text, "/etc/apt/sources.list.d/debian.sources")
    assert len(entries) == 2


def test_credentials_embedded_in_uri_are_redacted():
    text = "deb http://mirroruser:s3cr3t@mirror.example.com/debian trixie main\n"
    entries = apt_sources.parse_list_text(text, "/etc/apt/sources.list")
    assert len(entries) == 1
    assert "s3cr3t" not in entries[0]["uri"]
    assert "mirroruser" not in entries[0]["uri"]
    assert entries[0]["uri"] == "http://[REDACTED]@mirror.example.com/debian"


def test_deb822_credentials_in_uri_are_redacted():
    text = "Types: deb\nURIs: https://user:hunter2@repo.example.com/debian\nSuites: trixie\nComponents: main\n"
    entries = apt_sources.parse_deb822_text(text, "/etc/apt/sources.list.d/private.sources")
    assert len(entries) == 1
    assert "hunter2" not in entries[0]["uri"]


def test_collect_reads_legacy_and_both_deb822_and_list_fragments():
    r = FakeRunner()
    r.files["/etc/apt/sources.list"] = DEBIAN_TRIXIE_LIST
    r.dirs["/etc/apt/sources.list.d"] = ["pve-no-subscription.list", "pve-enterprise.sources", "readme.txt"]
    r.files["/etc/apt/sources.list.d/pve-no-subscription.list"] = PROXMOX_NO_SUBSCRIPTION_LIST
    r.files["/etc/apt/sources.list.d/pve-enterprise.sources"] = PROXMOX_ENTERPRISE_SOURCES_DISABLED
    # readme.txt is deliberately not a .list/.sources file and must be ignored.

    result = apt_sources.collect(r)
    formats = {e["format"] for e in result["entries"]}
    assert formats == {"list", "deb822"}
    assert len(result["entries"]) == 3 + 1 + 1  # 3 debian lines + 1 no-sub + 1 enterprise
    assert "/etc/apt/sources.list.d/readme.txt" not in [e["source_file"] for e in result["entries"]]
    channels = {e["channel"] for e in result["entries"]}
    assert "no-subscription" in channels
    assert "enterprise" in channels


def test_collect_missing_sources_list_d_is_reported_not_silently_empty():
    r = FakeRunner()
    r.files["/etc/apt/sources.list"] = DEBIAN_TRIXIE_LIST
    # /etc/apt/sources.list.d intentionally not registered in r.dirs

    result = apt_sources.collect(r)
    assert any("sources.list.d" in n["command"] for n in result["_collection_notes"])


def test_system_collect_apt_exposes_structured_repositories_not_raw_blob():
    from inventory.collectors.system import collect_apt
    r = FakeRunner()
    r.files["/etc/apt/sources.list"] = DEBIAN_TRIXIE_LIST
    r.dirs["/etc/apt/sources.list.d"] = []
    r.binaries["apt-cache"] = "/usr/bin/apt-cache"
    r.script(lambda a: a[:2] == ["apt-cache", "policy"], CommandResult(ok=True, stdout="500 ...\n"))

    result = collect_apt(r)
    assert "repositories" in result
    assert "sources_list" not in result
    assert len(result["repositories"]) == 3
