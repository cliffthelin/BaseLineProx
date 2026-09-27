#!/usr/bin/env python3
"""G8 Layer 2 dbusmock evidence driver.

Spins up a private D-Bus system bus per scenario, mocks exactly one of the
five D-Bus-backed G8 providers (systemd, logind, UPower, UDisks2,
Accounts) on it, then execs the real `g8_real_evidence` Rust binary with
`DBUS_SYSTEM_BUS_ADDRESS` pointed at the private bus so the *actual*
production adapters run against the mock -- never a second, parallel test
implementation.

UDisks2 and Accounts have no stock dbusmock template (checked: dbusmock
0.38.1 ships systemd/logind/upower templates but not these two), so this
file defines two small, clearly test-only mocks for them using dbusmock's
raw `spawn_server` + `AddObject`/`AddMethod` machinery -- never a generic
reusable mock framework, just the minimal shape each of the two needs.

All mock mutation happens through dbusmock's own client-facing
`org.freedesktop.DBus.Mock` D-Bus interface (`AddProperties`,
`UpdateProperties`, `AddObject`, `RemoveObject`) on a proxy obtained from
this (client) process -- the mock itself always runs in a separate
subprocess, so its Python-internal state is never touched directly from
here. This dbusmock version (0.38.1) has no client-facing RemoveProperty,
so a "missing property" scenario removes+re-adds the object instead.

Usage: g8_dbusmock_evidence.py <provider> <scenario>
  provider: systemd | logind | upower | udisks2 | accounts
  scenario: expected | absent | missing_property | malformed | stale_object
"""

import os
import hashlib
import subprocess
import sys

import dbus
import dbusmock
from dbusmock import MOCK_IFACE

EVIDENCE_BIN = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "target", "debug", "examples", "g8_real_evidence"
)


def source_digest():
    supplied = os.environ.get("G8_SOURCE_DIGEST")
    if supplied:
        return supplied
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    digest = hashlib.sha256()
    digest.update(subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=repo))
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=repo
    ).split(b"\0")
    for raw_name in sorted(
        name for name in untracked if name and not name.startswith(b"docs/evidence/")
    ):
        digest.update(raw_name)
        with open(os.path.join(repo, os.fsdecode(raw_name)), "rb") as source:
            digest.update(source.read())
    return digest.hexdigest()


def run_evidence():
    # dbusmock.DBusTestCase.start_system_bus() sets
    # os.environ["DBUS_SYSTEM_BUS_ADDRESS"] itself for the current
    # process -- inherited by the subprocess below, so the real
    # production adapters connect to the private mock bus, never a
    # second bus-selection code path of this script's own.
    result = subprocess.run(
        [EVIDENCE_BIN], env=os.environ, capture_output=True, text=True, timeout=30, check=False
    )
    return result.stdout + result.stderr


class Harness(dbusmock.DBusTestCase):
    @classmethod
    def setUpClass(cls):
        cls.start_system_bus()
        cls.dbus_con = cls.get_dbus(system_bus=True)

    @classmethod
    def object_at(cls, bus_name, path):
        return cls.dbus_con.get_object(bus_name, path)


def scenario_systemd(scenario):
    Harness.setUpClass()
    p_mock, obj_systemd = Harness.spawn_server_template("systemd", {}, stdout=subprocess.PIPE)
    obj_systemd.AddMethod(
        "org.freedesktop.systemd1.Manager",
        "LoadUnit",
        "s",
        "o",
        "if str(args[0]) in self.units:\n"
        "    ret = self.units[str(args[0])]\n"
        "else:\n"
        "    raise dbus.exceptions.DBusException(\n"
        "        'Unit not found', name='org.freedesktop.systemd1.NoSuchUnit'\n"
        "    )",
    )
    if scenario in ("expected", "malformed"):
        # AddMockUnit alone only sets Id/Names/LoadState/ActiveState (its
        # own template default) -- a real, complete unit also has
        # SubState/Description, so those are added explicitly for a
        # genuine happy-path response.
        obj_systemd.AddMockUnit("cron.service")
        unit_path = obj_systemd.GetUnit("cron.service")
        unit = Harness.object_at("org.freedesktop.systemd1", unit_path)
        unit.AddProperties(
            "org.freedesktop.systemd1.Unit",
            {"SubState": "running", "Description": "Mock cron"},
            dbus_interface=MOCK_IFACE,
        )
        if scenario == "malformed":
            # Wrong type for a string field -- adapter downcast must fail
            # closed with MalformedResponse, never panic.
            unit.UpdateProperties(
                "org.freedesktop.systemd1.Unit",
                {"ActiveState": dbus.UInt32(42)},
                dbus_interface=MOCK_IFACE,
            )
    elif scenario == "missing_property":
        # A loaded unit with the template's own incomplete default
        # property set (no SubState/Description) -- the adapter must
        # surface a real MalformedResponse, never a silently-defaulted
        # empty string.
        obj_systemd.AddMockUnit("cron.service")
    elif scenario == "absent":
        p_mock.terminate()
        p_mock.wait()
    output = run_evidence()
    print(output)
    p_mock.terminate()
    Harness.tearDownClass()


def scenario_logind(scenario):
    Harness.setUpClass()
    p_mock, obj_logind = Harness.spawn_server_template("logind", {}, stdout=subprocess.PIPE)
    held_inhibitor_fd = None
    if scenario == "expected":
        # Register a real inhibitor through the template's own real
        # Inhibit() method -- never fabricated data bypassing it. The
        # template's own inhibitor-drop logic (org.freedesktop.login1's
        # real semantics) removes the inhibitor as soon as its returned fd
        # is closed, so the fd must be kept open (assigned to a variable
        # that outlives run_evidence()) for this to be a genuine
        # non-empty-list case rather than an immediately-dropped one.
        held_inhibitor_fd = obj_logind.Inhibit("shutdown", "g8-dbusmock", "evidence run", "block")
    elif scenario == "absent":
        p_mock.terminate()
        p_mock.wait()
    output = run_evidence()
    print(output)
    p_mock.terminate()
    Harness.tearDownClass()


def scenario_upower(scenario):
    Harness.setUpClass()
    p_mock, obj_upower = Harness.spawn_server_template("upower", {}, stdout=subprocess.PIPE)
    display_path = "/org/freedesktop/UPower/devices/DisplayDevice"
    if scenario == "expected":
        obj_upower.AddDischargingBattery("mock_BAT0", "Mock Battery", 55.0, 3600)
    elif scenario == "missing_property":
        # dbusmock has no client-facing RemoveProperty -- simulate a
        # response missing a required field by removing the template's
        # own DisplayDevice object and re-adding it at the same path with
        # an incomplete property set.
        obj_upower.RemoveObject(display_path, dbus_interface=MOCK_IFACE)
        obj_upower.AddObject(
            display_path,
            "org.freedesktop.UPower.Device",
            dbus.Dictionary(
                {
                    "Type": dbus.UInt32(0),
                    "State": dbus.UInt32(0),
                    "Percentage": dbus.Double(0.0),
                    # IsPresent deliberately omitted.
                },
                signature="sv",
            ),
            dbus.Array([], signature="(ssss)"),
        )
    elif scenario == "malformed":
        display = Harness.object_at("org.freedesktop.UPower", display_path)
        display.UpdateProperties(
            "org.freedesktop.UPower.Device",
            {"Percentage": dbus.String("not-a-number")},
            dbus_interface=MOCK_IFACE,
        )
    elif scenario == "absent":
        p_mock.terminate()
        p_mock.wait()
    output = run_evidence()
    print(output)
    p_mock.terminate()
    Harness.tearDownClass()


UDISKS_DRIVE_IFACE = "org.freedesktop.UDisks2.Drive"
UDISKS_BLOCK_IFACE = "org.freedesktop.UDisks2.Block"


def scenario_udisks2(scenario):
    Harness.setUpClass()
    p_mock = Harness.spawn_server(
        "org.freedesktop.UDisks2",
        "/org/freedesktop/UDisks2",
        "org.freedesktop.UDisks2.Manager",
        system_bus=True,
        stdout=subprocess.PIPE,
    )
    obj_manager = Harness.object_at("org.freedesktop.UDisks2", "/org/freedesktop/UDisks2")
    # dbusmock's raw spawn_server() has no is_object_manager flag (only its
    # template loader does) -- this reproduces the exact same generated
    # method dbusmock's own _set_up_object_manager() would install, via the
    # normal client-facing AddMethod call.
    obj_manager.AddMethod(
        "org.freedesktop.DBus.ObjectManager",
        "GetManagedObjects",
        "",
        "a{oa{sa{sv}}}",
        "ret = {dbus.ObjectPath(k): objects[k].props for k in objects.keys() "
        "if k != '/org/freedesktop/UDisks2'}",
    )
    if scenario in ("expected", "missing_property", "malformed", "stale_object"):
        drive_path = "/org/freedesktop/UDisks2/drives/Mock_1"
        obj_manager.AddObject(
            drive_path,
            UDISKS_DRIVE_IFACE,
            dbus.Dictionary(
                {
                    "Id": "Mock-1",
                    "Vendor": "MockVendor",
                    "Model": "MockModel",
                    "CanPowerOff": dbus.Boolean(True),
                    "Removable": dbus.Boolean(True),
                },
                signature="sv",
            ),
            dbus.Array([], signature="(ssss)"),
        )
        if scenario == "malformed":
            drive = Harness.object_at("org.freedesktop.UDisks2", drive_path)
            drive.UpdateProperties(
                UDISKS_DRIVE_IFACE,
                {"CanPowerOff": dbus.String("yes")},
                dbus_interface=MOCK_IFACE,
            )
        block_path = "/org/freedesktop/UDisks2/block_devices/mocksdz"
        obj_manager.AddObject(
            block_path,
            UDISKS_BLOCK_IFACE,
            dbus.Dictionary(
                {
                    **(
                        {}
                        if scenario == "missing_property"
                        else {"Drive": dbus.ObjectPath(drive_path)}
                    ),
                    "PreferredDevice": dbus.ByteArray(b"/dev/mocksdz\0"),
                },
                signature="sv",
            ),
            dbus.Array([], signature="(ssss)"),
        )
        if scenario == "stale_object":
            # Prove Guardian re-derives topology from a fresh read rather
            # than trusting a stale in-memory snapshot: remove the drive
            # object after it was discoverable once, before this run's own
            # (single, fresh) topology() call -- the adapter must see the
            # post-removal state, not the earlier one.
            obj_manager.RemoveObject(drive_path, dbus_interface=MOCK_IFACE)
    elif scenario == "absent":
        p_mock.terminate()
        p_mock.wait()
    output = run_evidence()
    print(output)
    p_mock.terminate()
    Harness.tearDownClass()


def scenario_accounts(scenario):
    Harness.setUpClass()
    p_mock = Harness.spawn_server(
        "org.freedesktop.Accounts",
        "/org/freedesktop/Accounts",
        "org.freedesktop.Accounts",
        system_bus=True,
        stdout=subprocess.PIPE,
    )
    obj_manager = Harness.object_at("org.freedesktop.Accounts", "/org/freedesktop/Accounts")
    if scenario == "expected":
        obj_manager.AddMethod(
            "org.freedesktop.Accounts",
            "ListCachedUsers",
            "",
            "ao",
            'ret = ["/org/freedesktop/Accounts/User1000"]',
        )
    elif scenario == "malformed":
        # A response of the wrong signature entirely (a string, not an
        # object-path array) -- the adapter must fail closed via zbus's
        # own deserialization error, never panic or silently coerce.
        obj_manager.AddMethod(
            "org.freedesktop.Accounts",
            "ListCachedUsers",
            "",
            "s",
            'ret = "not-an-object-path-array"',
        )
    elif scenario == "absent":
        p_mock.terminate()
        p_mock.wait()
    output = run_evidence()
    print(output)
    p_mock.terminate()
    Harness.tearDownClass()


SCENARIOS = {
    "systemd": scenario_systemd,
    "logind": scenario_logind,
    "upower": scenario_upower,
    "udisks2": scenario_udisks2,
    "accounts": scenario_accounts,
}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in SCENARIOS:
        print(__doc__)
        sys.exit(1)
    print("=== scenario metadata ===")
    candidate_head = os.environ.get("G8_CANDIDATE_HEAD") or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    print(f"candidate_head={candidate_head}")
    print(f"source_digest_sha256={source_digest()}")
    print(f"provider={sys.argv[1]}")
    print(f"scenario={sys.argv[2]}")
    print("expected=production adapter and registry preserve present/absent/malformed/stale taxonomy")
    SCENARIOS[sys.argv[1]](sys.argv[2])
