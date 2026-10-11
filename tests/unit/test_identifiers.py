"""DR255: hierarchical identifiers. Pure minting and parsing, plus registry-backed minting (the registry is the test suite's isolated one)."""
import uuid

import pytest

import identifiers as idn

LANE = "4af8c95a-1c9b-437a-a306-c53855d4077f"
OTHER_LANE = "5029a80d-c748-4616-aa08-99ac560f5311"
PC601 = "FD01N6557110C271B"
PC401 = "MD89N41071210AP4E"


def hexpos(guid, start, stop):
    return guid.replace("-", "")[start:stop]


def test_a_host_identifier_has_the_layout_the_operator_described():
    host = idn.host_id(LANE, PC601)
    assert str(uuid.UUID(host)) == host
    assert hexpos(host, 0, 8) == "4af8c95a"          # first 8 of the installer lane
    assert hexpos(host, 8, 12) == "fd01"             # first 4 hex characters of the serial
    assert hexpos(host, 12, 16) == "271b"            # last 4 hex characters of the serial
    assert hexpos(host, 16, 17) == "1"               # layout version
    assert hexpos(host, 17, 18) == "0"               # kind: host
    assert idn.is_valid(host)


def test_non_hex_serial_characters_are_skipped_and_a_short_serial_is_filled_with_the_reserved_value():
    host = idn.host_id(LANE, PC401)                  # MD89N41071210AP4E: M, N, P are not hex digits
    assert hexpos(host, 8, 12) == "d894" and hexpos(host, 12, 16) == "0a4e"
    assert idn.serial_hex("GH1JKL2M", 4) == "1200" and idn.serial_hex("GH1JKL2M", 4, from_end=True) == "0012"


def test_the_host_identifier_of_pc601_is_pinned():
    assert idn.host_id(LANE, PC601) == "4af8c95a-fd01-271b-10be-bc48c28f0a00"


def test_the_same_inputs_always_give_the_same_identifier_and_different_inputs_do_not():
    host = idn.host_id(LANE, PC601)
    assert idn.host_id(LANE, PC601) == host
    assert idn.host_id(OTHER_LANE, PC601) != host and idn.host_id(LANE, PC401) != host
    a, b = idn.host_id(LANE, "ABCD11WXYZ22EF01"), idn.host_id(LANE, "ABCD33WXYZ44EF01")
    assert hexpos(a, 0, 16) == hexpos(b, 0, 16) and a != b          # same hint, still different drives


def test_substrate_and_vm_children_inherit_the_hosts_digits_and_add_their_own_id():
    host = idn.host_id(LANE, PC601)
    for kind, digit in (("substrate", "1"), ("vm", "2")):
        child = idn.child_id(host, kind, "ubuntu-desktop")
        assert hexpos(child, 0, 16) == hexpos(host, 0, 16)           # lane and serial hint: the ancestry
        assert hexpos(child, 17, 18) == digit and idn.is_valid(child)
        assert hexpos(child, 20, 24) == hexpos(host, 20, 24)         # the host discriminator
        assert hexpos(child, 24, 30) != hexpos(host, 24, 30) and hexpos(child, 30, 32) == "00"
    assert idn.child_id(host, "vm", "a") != idn.child_id(host, "vm", "b")
    assert idn.child_id(host, "vm", "a") != idn.child_id(host, "substrate", "a")
    assert idn.child_id(host, "vm", "a") == idn.child_id(host, "vm", "a")


def test_applications_and_hardware_drop_the_lane_for_a_parent_pointer_and_a_class_code():
    host = idn.host_id(LANE, PC601)
    vm = idn.child_id(host, "vm", "ubuntu-desktop")
    app = idn.child_id(vm, "application", "chrome/main")
    assert hexpos(app, 0, 4) == hexpos(vm, 24, 28)                   # pointer to the parent's own id
    assert hexpos(app, 4, 8) == idn.class_code("chrome")
    assert hexpos(app, 8, 16) == hexpos(host, 8, 16) and hexpos(app, 20, 24) == hexpos(host, 20, 24)   # the drive is still known
    assert hexpos(app, 17, 18) == "3" and idn.is_valid(app)
    assert idn.lane_prefix(app) is None and idn.lane_prefix(vm) == "4af8c95a"
    # the same application in another lane's VM has a different parent pointer, but the same class: components are lane-independent
    other = idn.child_id(idn.child_id(idn.host_id(OTHER_LANE, PC601), "vm", "ubuntu-desktop"), "application", "chrome/main")
    assert hexpos(other, 4, 8) == hexpos(app, 4, 8)
    hardware = idn.child_id(idn.child_id(host, "substrate", "baseline"), "hardware", "nic/ens3")
    assert hexpos(hardware, 17, 18) == "4" and idn.is_valid(hardware)


def test_class_codes_never_fall_in_the_reserved_low_range():
    for name in ("chrome", "vscode", "nic", "x", "a" * 40, "0", "z"):
        assert int(idn.class_code(name), 16) >= 0x0100


def test_an_identifier_can_be_read_back_into_its_fields():
    host = idn.host_id(LANE, PC601)
    vm = idn.child_id(host, "vm", "ubuntu-desktop")
    app = idn.child_id(vm, "application", "chrome/main")
    parsed = idn.parse(vm)
    assert (parsed.kind, parsed.lane, parsed.head, parsed.tail, parsed.version) == ("vm", "4af8c95a", "fd01", "271b", "1")
    assert idn.parse(host).kind == "host"
    assert idn.parse(app).kind == "application" and idn.parse(app).lane is None and idn.parse(app).class_code == idn.class_code("chrome")
    assert idn.same_drive(host, vm) and idn.same_drive(host, app)
    assert not idn.same_drive(host, idn.host_id(LANE, PC401))


def test_a_damaged_or_foreign_identifier_is_not_valid():
    host = idn.host_id(LANE, PC601)
    assert not idn.is_valid(host.replace("fd01", "fd02", 1))                       # a field changed: its check fails
    assert not idn.is_valid("4af8c95a-fd01-271b-b1ae-f19827f945b7")                # the earlier layout (version b)
    assert not idn.is_valid(str(uuid.uuid4())) and not idn.is_valid("not a uuid")
    with pytest.raises(idn.IdentifierError):
        idn.parse("not a uuid")


@pytest.mark.parametrize("serial", ["", "bad serial!", "x" * 65, "SHORT", "1234567"])
def test_a_serial_that_is_not_a_plain_serial_of_at_least_eight_characters_has_no_identifier(serial):
    with pytest.raises(idn.IdentifierError):
        idn.host_id(LANE, serial)


def test_only_sensible_parents_can_have_children():
    host = idn.host_id(LANE, PC601)
    app = idn.child_id(idn.child_id(host, "vm", "v"), "application", "chrome")
    with pytest.raises(idn.IdentifierError):
        idn.child_id(app, "vm", "nested")                  # a VM does not live under an application
    with pytest.raises(idn.IdentifierError):
        idn.child_id(host, "host", "x")
    with pytest.raises(idn.IdentifierError):
        idn.child_id(host, "bogus", "x")
    with pytest.raises(idn.IdentifierError):
        idn.child_id(host, "vm", "")


# --- registry-backed minting: one registry shape for every level ---------------------------------------------------------

def test_minting_registers_the_identifier_with_its_parent_and_is_idempotent():
    import registry
    host = idn.host_id(LANE, PC601)
    idn.register_host(host, serial=PC601)
    first = idn.mint(host, "vm", "ubuntu-desktop")
    assert first == idn.child_id(host, "vm", "ubuntu-desktop")
    assert idn.mint(host, "vm", "ubuntu-desktop") == first
    entries = registry.list_entries(idn.REGISTRY_TYPE, scope=registry.GLOBAL, read_only=True)
    assert len([g for g in entries if g == first]) == 1
    attrs = entries[first].get("attributes", entries[first])
    assert attrs["kind"] == "vm" and attrs["parent"] == host and attrs["name"] == "ubuntu-desktop" and attrs["serial"] == PC601


def test_a_collision_with_a_different_name_moves_to_the_next_counter_and_is_recorded():
    import registry
    host = idn.host_id(LANE, PC601)
    idn.register_host(host, serial=PC601)
    wanted = idn.child_id(host, "vm", "alpha")
    registry.register_type(idn.REGISTRY_TYPE, "x", default_scope=registry.GLOBAL)
    registry.upsert_entry(idn.REGISTRY_TYPE, wanted, scope=registry.GLOBAL,
                          attributes={"kind": "vm", "parent": host, "name": "SOMEONE-ELSE", "serial": PC601, "level": 2,
                                      "layout": "1", "counter": 0})
    minted = idn.mint(host, "vm", "alpha")
    assert minted != wanted and minted == idn.child_id(host, "vm", "alpha", counter=1)
    assert registry.get_entry(idn.REGISTRY_TYPE, minted, scope=registry.GLOBAL)["attributes"]["counter"] == 1


def test_everything_under_a_host_can_be_listed_from_its_digits():
    host = idn.host_id(LANE, PC601)
    other = idn.host_id(LANE, PC401)
    for h in (host, other):
        idn.register_host(h, serial=PC601 if h == host else PC401)
    vm = idn.mint(host, "vm", "ubuntu-desktop")
    app = idn.mint(vm, "application", "chrome/main")
    idn.mint(other, "vm", "someone-elses")
    assert sorted(idn.descendants(host)) == sorted([vm, app])


def test_the_last_byte_is_reserved_for_special_handling_and_ordinary_identifiers_carry_zero():
    host = idn.host_id(LANE, PC601)
    assert hexpos(host, 30, 32) == "00" and idn.parse(host).special == 0
    app = idn.child_id(host, "application", "chrome")
    assert idn.parse(app).special == 0
    flagged = idn.child_id(host, "vm", "x", special=0x80)
    assert idn.parse(flagged).special == 0x80 and idn.is_valid(flagged) and flagged != idn.child_id(host, "vm", "x")
    with pytest.raises(idn.IdentifierError):
        idn.child_id(host, "vm", "x", special=256)


def test_an_external_uuid_maps_to_a_stable_but_not_derivable_identifier_through_the_cross_map():
    host = idn.host_id(LANE, PC601)
    idn.register_host(host, serial=PC601)
    outside = "9b1d6f0e-3a54-4c1f-8f6e-0a1b2c3d4e5f"
    first = idn.map_external(host, "vm", "imported-disk", outside)
    assert idn.is_valid(first) and idn.parse(first).special == idn.SPECIAL["external"]
    assert idn.map_external(host, "vm", "imported-disk", outside) == first          # stable once recorded
    assert idn.lookup_external(outside) == first and idn.external_of(first) == "uuid:" + outside
    other = idn.map_external(host, "vm", "other", "11111111-2222-4333-8444-555555555555")
    assert other != first
    assert idn.lookup_external("not-a-uuid") is None


def test_every_kind_of_external_identifier_maps_by_its_scheme_and_the_schemes_do_not_collide():
    host = idn.host_id(LANE, PC601)
    idn.register_host(host, serial=PC601)
    same = "9b1d6f0e-3a54-4c1f-8f6e-0a1b2c3d4e5f"
    part = idn.map_external(host, "hardware", "sda1", same, scheme="partuuid")
    fs = idn.map_external(host, "hardware", "sda1-fs", same, scheme="fsuuid")
    assert part != fs and idn.lookup_external(same, scheme="partuuid") == part and idn.lookup_external(same) is None
    nic = idn.map_external(host, "hardware", "ens3", "AA:BB:CC:00:11:22", scheme="mac")
    assert idn.lookup_external("aa:bb:cc:00:11:22", scheme="mac") == nic and idn.external_of(nic) == "mac:aa:bb:cc:00:11:22"
    assert idn.lookup_external("120", scheme="vmid") is None
    assert idn.map_external(host, "vm", "base", "120", scheme="vmid") == idn.lookup_external("120", scheme="vmid")
    with pytest.raises(idn.IdentifierError):
        idn.map_external(host, "hardware", "x", "nope", scheme="partuuid")
    with pytest.raises(idn.IdentifierError):
        idn.map_external(host, "hardware", "x", same, scheme="bogus")


def test_a_portable_identifier_is_deterministic_keeps_its_digits_and_can_change_parent():
    host_a, host_b = idn.host_id(LANE, PC601), idn.host_id(LANE, PC401)
    idn.register_host(host_a, serial=PC601)
    idn.register_host(host_b, serial=PC401)
    store = idn.mint_portable(host_a, "substrate", "USER_PERSISTENCE_ADMIN")
    assert store == idn.mint_portable(host_a, "substrate", "USER_PERSISTENCE_ADMIN") == idn.child_id(host_a, "substrate", "USER_PERSISTENCE_ADMIN", special=2)
    assert idn.parse(store).special == idn.SPECIAL["portable"] and idn.is_valid(store)
    assert store != idn.mint(host_a, "substrate", "USER_PERSISTENCE_ADMIN")
    idn.reparent(store, host_b)
    assert idn.descendants(host_b) == [store] and store not in idn.descendants(host_a)
    assert idn.mint_portable(host_a, "substrate", "USER_PERSISTENCE_ADMIN") == store      # same identifier after the move


def test_only_a_portable_identifier_may_change_parent():
    host_a, host_b = idn.host_id(LANE, PC601), idn.host_id(LANE, PC401)
    idn.register_host(host_a, serial=PC601)
    idn.register_host(host_b, serial=PC401)
    fixed = idn.mint(host_a, "substrate", "SESSION_TEMP")
    with pytest.raises(idn.IdentifierError):
        idn.reparent(fixed, host_b)
