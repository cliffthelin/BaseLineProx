import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "baseline" / "lib"))
SCRIPT = ROOT / "baseline" / "bin" / "baseline-setup-wizard"
LOADER = importlib.machinery.SourceFileLoader("baseline_setup_wizard_test", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
WIZARD = importlib.util.module_from_spec(SPEC)


class _Console:
    def print(self, *_args, **_kwargs):
        pass


class _Prompt:
    @staticmethod
    def ask(*_args, **_kwargs):
        raise AssertionError("Prompt.ask must be patched by the test")


class _Confirm:
    @staticmethod
    def ask(*_args, **_kwargs):
        raise AssertionError("Confirm.ask must be patched by the test")


rich_modules = {
    "rich": types.ModuleType("rich"),
    "rich.console": types.ModuleType("rich.console"),
    "rich.prompt": types.ModuleType("rich.prompt"),
    "rich.panel": types.ModuleType("rich.panel"),
}
rich_modules["rich.console"].Console = _Console
rich_modules["rich.prompt"].Confirm = _Confirm
rich_modules["rich.prompt"].Prompt = _Prompt
rich_modules["rich.panel"].Panel = lambda *args, **kwargs: (args, kwargs)
old_rich_modules = {name: sys.modules.get(name) for name in rich_modules}
sys.modules.update(rich_modules)
try:
    LOADER.exec_module(WIZARD)
finally:
    for name, old_module in old_rich_modules.items():
        if old_module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = old_module


def test_restore_does_not_claim_success_when_plaintext_staging_cleanup_fails(tmp_path, monkeypatch):
    packet = tmp_path / "handoff.gpg"
    packet.write_bytes(b"encrypted packet")
    staging = tmp_path / "staging"
    manifest = {
        "host_label": "test-host",
        "created": "2026-10-09T00:00:00Z",
        "has_harness_token": True,
        "has_interface_aliases": False,
        "files_included": ["secret-token"],
    }

    monkeypatch.setattr(WIZARD.Prompt, "ask", lambda *_args, **_kwargs: str(packet))
    monkeypatch.setattr(WIZARD.Confirm, "ask", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(WIZARD.getpass, "getpass", lambda *_args, **_kwargs: "throwaway")
    real_path = Path
    def isolated_path(value):
        if str(value) == "/root/.baseline-handoff-restore":
            return staging
        if str(value) == "/mnt":
            return tmp_path / "mnt"
        return real_path(value)

    monkeypatch.setattr(WIZARD, "Path", isolated_path)

    def open_packet(_packet, _passphrase, destination):
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "plaintext-secret").write_text("secret")
        return manifest

    monkeypatch.setattr(WIZARD.handoff, "open_packet", open_packet)
    monkeypatch.setattr(WIZARD, "_apply_extracted", lambda _path: None)

    def fail_cleanup(_path, *, ignore_errors=False, **_kwargs):
        if ignore_errors:
            return None
        raise OSError("simulated secure-staging cleanup failure")

    monkeypatch.setattr(WIZARD.shutil, "rmtree", fail_cleanup)
    with pytest.raises((OSError, RuntimeError), match="cleanup"):
        WIZARD.restore_from_packet()


def test_hostname_apply_rolls_back_persistent_file_when_live_change_fails(tmp_path, monkeypatch):
    hostname_file = tmp_path / "etc" / "hostname"
    hostname_file.parent.mkdir()
    hostname_file.write_text("old-host\n")
    real_path = Path
    monkeypatch.setattr(WIZARD, "Path", lambda value: hostname_file if str(value) == "/etc/hostname" else real_path(value))
    monkeypatch.setattr(WIZARD.socket, "sethostname", lambda _name: (_ for _ in ()).throw(OSError("capability denied")))

    with pytest.raises((OSError, RuntimeError), match="hostname"):
        WIZARD.apply_form({"hostname": "new-host"})

    assert hostname_file.read_text() == "old-host\n"


def test_hostname_apply_rolls_back_live_value_when_file_write_fails(tmp_path, monkeypatch):
    hostname_file = tmp_path / "etc" / "hostname"
    hostname_file.parent.mkdir()
    hostname_file.write_text("old-host\n")
    real_path = Path
    monkeypatch.setattr(WIZARD, "Path", lambda value: hostname_file if str(value) == "/etc/hostname" else real_path(value))
    real_write_text = Path.write_text
    writes = 0

    def fail_first_write(path, content, *args, **kwargs):
        nonlocal writes
        if path == hostname_file:
            writes += 1
            if writes == 1:
                raise OSError("read-only filesystem")
        return real_write_text(path, content, *args, **kwargs)

    calls = []
    monkeypatch.setattr(Path, "write_text", fail_first_write)
    monkeypatch.setattr(WIZARD.socket, "sethostname", lambda name: calls.append(name))

    with pytest.raises(RuntimeError, match="persist hostname"):
        WIZARD.apply_form({"hostname": "new-host"})

    assert hostname_file.read_text() == "old-host\n"
    assert calls == ["new-host", WIZARD.socket.gethostname()]


def test_packet_apply_rolls_back_prior_files_when_a_later_copy_fails(tmp_path, monkeypatch):
    extract = tmp_path / "extract"
    (extract / "etc-baseline").mkdir(parents=True)
    (extract / "etc-baseline" / "existing.conf").write_text("packet version\n")
    (extract / "etc-baseline" / "new.conf").write_text("new packet file\n")
    (extract / "root-ssh").mkdir()
    (extract / "root-ssh" / "id_rsa").write_text("new private key\n")

    root = tmp_path / "target-root"
    baseline = root / "etc" / "baseline"
    baseline.mkdir(parents=True)
    (baseline / "existing.conf").write_text("machine version\n")
    ssh = root / "root" / ".ssh"
    ssh.mkdir(parents=True)
    (ssh / "id_rsa").write_text("machine private key\n")

    destination_map = {
        "/etc/baseline": baseline,
        "/var/lib/baseline": root / "var" / "lib" / "baseline",
        "/var/log/baseline": root / "var" / "log" / "baseline",
        "/etc/ssh": root / "etc" / "ssh",
        "/root/.ssh": ssh,
    }
    real_path = Path
    monkeypatch.setattr(WIZARD, "Path", lambda value: destination_map.get(str(value), real_path(value)))
    real_copy2 = WIZARD.shutil.copy2
    injected_failures = []

    def fail_on_private_key(source, destination, *args, **kwargs):
        if Path(source).name == "id_rsa" and Path(source).parent.name == "root-ssh":
            injected_failures.append(source)
            raise OSError("simulated later restore copy failure")
        return real_copy2(source, destination, *args, **kwargs)

    monkeypatch.setattr(WIZARD.shutil, "copy2", fail_on_private_key)
    with pytest.raises(OSError, match="later restore copy failure"):
        WIZARD._apply_extracted(extract)

    assert injected_failures
    assert (baseline / "existing.conf").read_text() == "machine version\n"
    assert not (baseline / "new.conf").exists()
    assert (ssh / "id_rsa").read_text() == "machine private key\n"


def test_packet_apply_merges_files_and_preserves_unrelated_machine_state(tmp_path, monkeypatch):
    extract = tmp_path / "extract"
    packet_baseline = extract / "etc-baseline"
    packet_baseline.mkdir(parents=True)
    (packet_baseline / "managed.conf").write_text("packet config\n")
    packet_ssh = extract / "root-ssh"
    packet_ssh.mkdir()
    (packet_ssh / "id_rsa").write_text("packet private key\n")

    root = tmp_path / "target-root"
    baseline = root / "etc" / "baseline"
    baseline.mkdir(parents=True)
    (baseline / "unrelated.conf").write_text("keep me\n")
    ssh = root / "root" / ".ssh"
    destination_map = {
        "/etc/baseline": baseline,
        "/var/lib/baseline": root / "var" / "lib" / "baseline",
        "/var/log/baseline": root / "var" / "log" / "baseline",
        "/etc/ssh": root / "etc" / "ssh",
        "/root/.ssh": ssh,
    }
    real_path = Path
    monkeypatch.setattr(WIZARD, "Path", lambda value: destination_map.get(str(value), real_path(value)))

    WIZARD._apply_extracted(extract)

    assert (baseline / "managed.conf").read_text() == "packet config\n"
    assert (baseline / "unrelated.conf").read_text() == "keep me\n"
    assert (ssh / "id_rsa").read_text() == "packet private key\n"
    assert (ssh / "id_rsa").stat().st_mode & 0o777 == 0o600
    assert ssh.stat().st_mode & 0o777 == 0o700


def test_packet_apply_refuses_unrecognized_ssh_configuration_files(tmp_path, monkeypatch):
    extract = tmp_path / "extract"
    (extract / "etc-baseline").mkdir(parents=True)
    (extract / "etc-baseline" / "managed.conf").write_text("packet config\n")
    packet_ssh = extract / "ssh-host-keys"
    packet_ssh.mkdir()
    (packet_ssh / "sshd_config").write_text("unreviewed ssh configuration\n")

    root = tmp_path / "target-root"
    baseline = root / "etc" / "baseline"
    baseline.mkdir(parents=True)
    (baseline / "managed.conf").write_text("machine config\n")
    ssh = root / "etc" / "ssh"
    ssh.mkdir(parents=True)
    (ssh / "sshd_config").write_text("machine ssh configuration\n")
    destination_map = {
        "/etc/baseline": baseline,
        "/var/lib/baseline": root / "var" / "lib" / "baseline",
        "/var/log/baseline": root / "var" / "log" / "baseline",
        "/etc/ssh": ssh,
        "/root/.ssh": root / "root" / ".ssh",
    }
    real_path = Path
    monkeypatch.setattr(WIZARD, "Path", lambda value: destination_map.get(str(value), real_path(value)))

    with pytest.raises(RuntimeError, match="SSH key"):
        WIZARD._apply_extracted(extract)

    assert (baseline / "managed.conf").read_text() == "machine config\n"
    assert (ssh / "sshd_config").read_text() == "machine ssh configuration\n"
