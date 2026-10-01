"""Unit tests for naming.py - constant, fixed-length identifiers
(<L>_<M>_<NNNNN>) with human names only as aliases.

The registry is isolated per test by conftest.py's autouse fixture, so
every allocation here is real but disposable.
"""
import pytest

import naming as nm


# -- Format ------------------------------------------------------------

def test_every_identifier_is_exactly_nine_characters():
    assert len(nm.format_id("A", "C", "00001")) == nm.ID_LENGTH == 9


def test_format_is_cluster_underscore_medium_underscore_code():
    assert nm.format_id("A", "C", "00001") == "A_C_00001"
    assert nm.format_id("O", "I", "00001") == "O_I_00001"


def test_identifier_always_fits_an_ext4_label():
    """Every old name that ran past 16 characters truncated; the persona
    volumes even collided. A fixed 9 can never truncate."""
    assert nm.ID_LENGTH <= 16


@pytest.mark.parametrize("cluster", ["U", "A", "S", "O"])
def test_each_layer_cluster_is_accepted(cluster):
    assert nm.parse_id(nm.format_id(cluster, "D", "00001")).cluster == cluster


@pytest.mark.parametrize("medium", ["D", "C", "L", "V", "F", "A", "S", "N", "I"])
def test_each_medium_is_accepted(medium):
    assert nm.parse_id(nm.format_id("A", medium, "00001")).medium == medium


def test_iso_is_a_medium():
    assert nm.MEDIA["I"] == "ISO image"


@pytest.mark.parametrize("bad", [
    ("X", "C", "00001"),     # unknown cluster
    ("A", "Z", "00001"),     # unknown medium
    ("A", "C", "0001"),      # code too short
    ("A", "C", "000001"),    # code too long
    ("A", "C", "caddy"),     # lowercase - would break the uid mapping
    ("A", "C", "00-01"),     # punctuation
])
def test_invalid_parts_are_refused(bad):
    with pytest.raises(nm.NamingError):
        nm.format_id(*bad)


def test_a_human_name_is_never_part_of_the_identifier():
    """The identifier is only ever the code."""
    for value in ("caddy", "A_C_caddy", "caddy_A_C_00001", "A-C-00001"):
        assert nm.is_id(value) is False


def test_parse_round_trips():
    parsed = nm.parse_id("A_L_00042")
    assert (parsed.cluster, parsed.medium, parsed.code) == ("A", "L", "00042")
    assert str(parsed) == "A_L_00042"


def test_separator_is_one_systemd_leaves_unescaped():
    """`_` passes systemd unit-name escaping; `-` would become \\x2d."""
    assert nm.SEPARATOR == "_"
    assert "-" not in nm.format_id("A", "C", "00001")


def test_owner_name_is_lowercase_and_one_to_one():
    """Uppercase-only codes make lowercasing a bijection, so two
    identifiers can never share an owner uid."""
    a = nm.parse_id("A_C_0000A").owner_name
    b = nm.parse_id("A_C_00001").owner_name
    assert a == "baseline-a_c_0000a" and a != b
    assert len(a) <= 32          # useradd's limit


# -- Allocation --------------------------------------------------------

def test_first_allocation_in_a_cluster_is_00001():
    assert nm.allocate("A", "C", "caddy") == "A_C_00001"


def test_allocation_is_idempotent_per_subject():
    first = nm.allocate("A", "C", "caddy")
    assert nm.allocate("A", "C", "caddy") == first


def test_codes_are_unique_per_cluster_across_media():
    """A number alone identifies one thing within its cluster."""
    assert nm.allocate("A", "C", "caddy") == "A_C_00001"
    assert nm.allocate("A", "L", "pihole") == "A_L_00002"
    assert nm.allocate("A", "F", "firefox") == "A_F_00003"


def test_clusters_number_independently():
    nm.allocate("A", "C", "caddy")
    assert nm.allocate("O", "I", "proxmox-ve") == "O_I_00001"


def test_a_retired_code_is_never_handed_out_again():
    """Recomputing numbers from the live set would reuse or shift them -
    the hazard that renumbered a real partition."""
    first = nm.allocate("A", "C", "caddy")
    nm.retire(first)
    assert nm.is_retired(first)
    assert nm.allocate("A", "C", "something-else") == "A_C_00002"


def test_retiring_keeps_the_entry():
    value = nm.allocate("A", "C", "caddy")
    nm.retire(value)
    assert value in nm.allocated()


def test_an_explicit_five_character_code_can_be_chosen():
    assert nm.allocate("A", "C", "caddy", code="CADDY") == "A_C_CADDY"


def test_an_explicit_code_cannot_collide():
    nm.allocate("A", "C", "caddy", code="CADDY")
    with pytest.raises(nm.NamingError):
        nm.allocate("A", "D", "other", code="CADDY")


def test_numeric_allocation_skips_an_explicitly_taken_number():
    nm.allocate("A", "C", "x", code="00001")
    assert nm.allocate("A", "C", "y") == "A_C_00002"


def test_allocations_survive_as_registry_entries():
    value = nm.allocate("A", "C", "caddy")
    entry = nm.allocated()[value]
    assert entry["attributes"]["subject"] == "caddy"
    assert entry["value"] == {"retired": False}


def test_retiring_an_unknown_identifier_is_refused():
    with pytest.raises(nm.NamingError):
        nm.retire("A_C_09999")


def test_numeric_space_is_bounded():
    with pytest.raises(nm.NamingError):
        nm.numeric_code(nm.MAX_NUMERIC + 1)


# -- Aliases -----------------------------------------------------------

def test_alias_is_a_relative_symlink_under_by_name():
    link = nm.alias_link("/mnt/APPDATA_PERSONAL", "caddy", "A_C_00001")
    assert link.link == "/mnt/APPDATA_PERSONAL/by-name/caddy"
    assert link.target == "../A_C_00001"


def test_aliases_are_per_base_so_two_people_can_share_a_name():
    a = nm.alias_link("/mnt/APPDATA_ADMIN", "notes", "A_D_00007")
    b = nm.alias_link("/mnt/APPDATA_PERSONAL", "notes", "A_D_00008")
    assert a.link != b.link


def test_alias_directories_are_root_owned_and_not_app_writable():
    link = nm.alias_link("/mnt/APPDATA_PERSONAL", "caddy", "A_C_00001")
    assert link.owner == "root"
    assert link.dir_mode == "0755"


def test_an_alias_may_not_look_like_an_identifier():
    """by-name/A_C_00002 -> ../A_C_00001 would mislead anyone reading."""
    with pytest.raises(nm.NamingError):
        nm.validate_alias("A_C_00002")


@pytest.mark.parametrize("bad", ["", ".", "..", "../etc", "a/b", "-leading", "x" * 64, "has space"])
def test_unsafe_aliases_are_refused(bad):
    with pytest.raises(nm.NamingError):
        nm.validate_alias(bad)


# -- Mounts never go through an alias ----------------------------------

def test_a_canonical_path_passes():
    path = nm.canonical_path("/mnt/APPDATA_PERSONAL", "A_C_00001")
    assert nm.assert_canonical(path) == "/mnt/APPDATA_PERSONAL/A_C_00001"


def test_a_path_through_an_alias_is_refused():
    """A symlink is followed at mount time; if it could be repointed, a
    mount could be redirected into another app's data."""
    with pytest.raises(nm.NamingError):
        nm.assert_canonical("/mnt/APPDATA_PERSONAL/by-name/caddy/binds/data")
