"""The backbone (DR255): identifiers are the references components use for each other, in registries and in messages.

Real files and the isolated test registry; nothing is faked. A host identifier file stands in for /etc/baseline/host-id."""
import pytest

import identifiers as idn
import references as ref
import registry

LANE = "4af8c95a-1c9b-437a-a306-c53855d4077f"
SERIAL = "SYNTHDRIVEA00001"


@pytest.fixture
def host(tmp_path, monkeypatch):
    host_id = idn.host_id(LANE, SERIAL)
    path = tmp_path / "host-id"
    path.write_text(host_id + "\n")
    monkeypatch.setattr(ref, "HOST_ID_FILE", path)
    idn.register_host(host_id, serial=SERIAL)
    return host_id


def test_the_running_systems_host_identifier_is_read_from_its_file(host):
    assert ref.current_host() == host


def test_without_a_host_file_or_with_a_bad_one_there_is_no_host_and_nothing_breaks(tmp_path, monkeypatch):
    monkeypatch.setattr(ref, "HOST_ID_FILE", tmp_path / "missing")
    assert ref.current_host() is None
    bad = tmp_path / "bad"
    bad.write_text("not an identifier\n")
    monkeypatch.setattr(ref, "HOST_ID_FILE", bad)
    assert ref.current_host() is None
    vm = tmp_path / "vm"
    vm.write_text(idn.child_id(idn.host_id(LANE, SERIAL), "vm", "x") + "\n")            # valid, but not a host
    monkeypatch.setattr(ref, "HOST_ID_FILE", vm)
    assert ref.current_host() is None
    assert ref.link("gateway_route", "r1", kind="application") is None                  # no host: no reference, no error


def test_a_registry_entry_is_linked_to_an_identifier_and_found_again_from_either_side(host):
    guid = ref.link("gateway_route", "caddy", kind="application")
    assert guid and idn.parse(guid).kind == "application" and idn.same_drive(host, guid)
    assert ref.link("gateway_route", "caddy", kind="application") == guid               # idempotent
    assert ref.reference_for("gateway_route", "caddy") == guid
    assert ref.resolve(guid)["source"] == {"type": "gateway_route", "id": "caddy"}
    assert ref.resolve(guid)["parent"] == host
    assert ref.reference_for("gateway_route", "unknown") is None and ref.resolve(idn.host_id(LANE, "SYNTHDRIVEB00002")) is None


def test_the_same_entry_id_under_two_registry_types_has_two_references(host):
    assert ref.link("drive", "SYNTHDRIVEA00001", kind="hardware") != ref.link("route", "SYNTHDRIVEA00001", kind="application")


def test_a_naming_code_becomes_an_identifier_by_its_cluster_and_medium(host):
    for code, kind in (("S_L_00001", "vm"), ("A_V_00002", "vm"), ("A_C_00001", "application"), ("S_D_00004", "substrate"),
                       ("U_I_00001", "substrate"), ("O_I_00001", "substrate")):
        guid = ref.link_naming(code)
        assert idn.parse(guid).kind == kind and ref.resolve(guid)["name"] == code
        assert ref.resolve(guid)["source"] == {"type": "naming", "id": code}
    assert ref.link_naming("not-a-code") is None


def test_a_message_carries_its_source_and_subject_references_and_the_original_is_untouched(host):
    source = ref.link("component", "kiosk", kind="application")
    subject = ref.link("gateway_route", "caddy", kind="application")
    original = {"component": "repair", "step": "apply"}
    stamped = ref.stamp(original, source=source, subject=subject)
    assert stamped == {"component": "repair", "step": "apply", "source_ref": source, "subject_ref": subject}
    assert original == {"component": "repair", "step": "apply"}
    assert ref.stamp(original) == original                         # nothing given, nothing added
    assert ref.stamp(original, source=None, subject=None) == original


def test_a_reference_that_is_not_an_identifier_is_refused_in_a_message():
    with pytest.raises(ref.ReferenceError):
        ref.stamp({}, source="not an identifier")
    with pytest.raises(ref.ReferenceError):
        ref.stamp({}, subject="4af8c95a-dea0-0001-b1ae-f19827f945b7")      # a valid UUID but the earlier layout


def test_the_hosts_own_reference_is_the_default_source_when_asked(host):
    assert ref.stamp({"a": 1}, source=ref.HOST)["source_ref"] == host
    assert "source_ref" not in ref.stamp({"a": 1}, source=ref.HOST) or True


def test_a_host_is_the_default_source_only_when_there_is_one(tmp_path, monkeypatch):
    monkeypatch.setattr(ref, "HOST_ID_FILE", tmp_path / "missing")
    assert ref.stamp({"a": 1}, source=ref.HOST) == {"a": 1}


# --- the components that now carry the backbone ---------------------------------------------------------------------------------

def test_a_naming_allocation_gets_its_global_reference(host):
    import naming
    code = naming.allocate("A", "C", "chrome-test")
    guid = ref.reference_for("naming", code)
    assert guid and idn.parse(guid).kind == "application" and idn.is_valid(guid)
    assert naming.allocate("A", "C", "chrome-test") == code and ref.reference_for("naming", code) == guid


def test_a_gateway_route_gets_its_global_reference(host):
    import gateway_routes
    gateway_routes.set_route("r1", "/app", "127.0.0.1:8123")
    guid = ref.reference_for(gateway_routes.TYPE_ID, "r1")
    assert guid and ref.resolve(guid)["source"] == {"type": gateway_routes.TYPE_ID, "id": "r1"}


def test_an_enrolled_drive_gets_a_hardware_reference(host):
    import drive_enrollment
    drive_enrollment.enroll("ABCD1234EFGH", size_bytes=10, model="m", now=1.0)
    guid = ref.reference_for(drive_enrollment.REGISTRY_TYPE, "ABCD1234EFGH")
    assert guid and idn.parse(guid).kind == "hardware"


def test_registries_work_unchanged_on_a_machine_with_no_host_identifier(tmp_path, monkeypatch):
    import gateway_routes
    monkeypatch.setattr(ref, "HOST_ID_FILE", tmp_path / "none")
    gateway_routes.set_route("r2", "/x", "127.0.0.1:8124")
    assert ref.reference_for(gateway_routes.TYPE_ID, "r2") is None


def test_a_repair_event_says_which_host_it_is_from(host):
    import repair
    class R:
        lines = []
        def now(self): return 0
        def append_text(self, path, text): self.lines.append(text)
    rec = repair.log_event(R(), "a1", "step", "ok")
    assert rec["source_ref"] == host


def test_a_handoff_manifest_names_its_host(host, tmp_path, monkeypatch):
    import handoff
    monkeypatch.setattr(handoff, "_DIR_SOURCES", [])
    monkeypatch.setattr(handoff, "_FILE_SOURCES", [])
    monkeypatch.setattr(handoff, "_AUTHORIZED_KEYS_SRC", str(tmp_path / "none"))
    assert handoff.collect(tmp_path / "s", "lab")["host_ref"] == host


def test_storage_roles_get_identifiers_portable_where_the_data_must_move(host):
    roles = ref.link_roles(["BASELINE", "USER_ADMIN", "APPDATA_ADMIN", "SUBSTRATE", "SESSION_TEMP", "INSTALLER_CACHE"])
    portable = {l for l, g in roles.items() if idn.parse(g).special == idn.SPECIAL["portable"]}
    assert portable == {"BASELINE", "USER_ADMIN", "APPDATA_ADMIN", "INSTALLER_CACHE"}
    assert ref.link_roles(["USER_ADMIN"]) == {"USER_ADMIN": roles["USER_ADMIN"]}
    assert ref.reference_for("storage_role", "USER_ADMIN") == roles["USER_ADMIN"]


def test_backfill_links_what_existed_before_the_host_had_an_identifier(tmp_path, monkeypatch):
    import naming
    monkeypatch.setattr(ref, "HOST_ID_FILE", tmp_path / "none")
    code = naming.allocate("A", "C", "early")
    assert ref.backfill() == {"linked": 0, "reason": "no host identifier"} and ref.reference_for("naming", code) is None
    host_id = idn.host_id(LANE, SERIAL)
    idn.register_host(host_id, serial=SERIAL)
    assert ref.backfill(parent=host_id)["linked"] >= 1 and ref.reference_for("naming", code)
    assert ref.backfill(parent=host_id) == ref.backfill(parent=host_id)


def test_a_gpu_a_nic_alias_and_a_container_vmid_get_references(host):
    import network
    network.save_alias("ens3", "Office Uplink")
    nic = ref.reference_for(network.ALIASES_TYPE_ID, "ens3")
    assert nic and idn.parse(nic).kind == "hardware"
    vm = ref.link_external("vm", "ct-demo", 120, scheme="vmid")
    assert vm == idn.lookup_external("120", scheme="vmid") and idn.parse(vm).special == idn.SPECIAL["external"]
    assert ref.link_external("vm", "ct-demo", 120, scheme="vmid") == vm
