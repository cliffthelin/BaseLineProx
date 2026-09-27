"""Unit tests for quadlet.py - Track B4, Podman + Quadlet service
management. No real podman, no real systemctl - see fake_runner.FakeRunner."""
from fake_runner import FakeRunner, FakeProc

import quadlet
from quadlet import ContainerSpec


def test_generate_unit_minimal():
    spec = ContainerSpec(name="pihole", image="docker.io/pihole/pihole:latest")
    content = quadlet.generate_unit(spec)
    assert "[Container]" in content
    assert "Image=docker.io/pihole/pihole:latest" in content
    assert "ContainerName=pihole" in content
    assert "[Install]" in content
    assert "WantedBy=multi-user.target" in content


def test_generate_unit_includes_all_optional_fields():
    spec = ContainerSpec(
        name="guardian-web",
        image="localhost/guardian-web:latest",
        description="Guardian's local dashboard",
        command=["node", "server.js"],
        volumes=["/var/lib/baseline/guardian:/data"],
        environment={"PORT": "8100", "NODE_ENV": "production"},
        network="host",
        publish=["8100:8100"],
        auto_update="registry",
    )
    content = quadlet.generate_unit(spec)
    assert "Description=Guardian's local dashboard" in content
    assert "Exec=node server.js" in content
    assert "Volume=/var/lib/baseline/guardian:/data" in content
    assert "Environment=NODE_ENV=production" in content
    assert "Environment=PORT=8100" in content
    assert "Network=host" in content
    assert "PublishPort=8100:8100" in content
    assert "AutoUpdate=registry" in content


def test_generate_unit_is_pure_no_io():
    # calling it twice with the same spec must be byte-identical -
    # proof there's no hidden clock/randomness/filesystem read inside.
    spec = ContainerSpec(name="a", image="b")
    assert quadlet.generate_unit(spec) == quadlet.generate_unit(spec)


def test_unit_path():
    assert quadlet.unit_path("pihole") == "/etc/containers/systemd/pihole.container"


def test_is_podman_installed_true():
    runner = FakeRunner()
    runner.script_prefix("podman", returncode=0, stdout="podman version 5.7.0", stderr="")
    assert quadlet.is_podman_installed(runner) is True


def test_is_podman_installed_false():
    runner = FakeRunner()
    runner.script_prefix("podman", returncode=127, stdout="", stderr="command not found")
    assert quadlet.is_podman_installed(runner) is False


def test_write_and_start_refuses_when_podman_missing():
    runner = FakeRunner()
    runner.script_prefix("podman", returncode=127, stdout="", stderr="not found")
    result = quadlet.write_and_start(runner, ContainerSpec(name="pihole", image="pihole/pihole"))
    assert result.applied is False
    assert "podman is not installed" in result.detail
    assert runner.writes == []


def test_write_and_start_writes_reloads_and_starts():
    runner = FakeRunner()
    runner.script_prefix("podman", returncode=0, stdout="podman version 5.7.0", stderr="")
    runner.script_prefix("systemctl", returncode=0, stdout="", stderr="")
    result = quadlet.write_and_start(runner, ContainerSpec(name="pihole", image="pihole/pihole"))
    assert result.applied is True
    assert quadlet.unit_path("pihole") in runner.files
    assert ["systemctl", "daemon-reload"] in runner.calls
    # Deliberately `start`, never `enable` - see write_and_start's own
    # docstring: a real QEMU test found `systemctl enable` refuses a
    # Quadlet-generated (transient) unit outright.
    assert ["systemctl", "start", "pihole.service"] in runner.calls
    assert not any(call[:2] == ["systemctl", "enable"] for call in runner.calls)


def test_write_and_start_reports_failed_daemon_reload():
    runner = FakeRunner()
    runner.script_prefix("podman", returncode=0, stdout="podman version 5.7.0", stderr="")
    runner.script(lambda a: a[:2] == ["systemctl", "daemon-reload"], FakeProc(1, "", "reload error"))
    result = quadlet.write_and_start(runner, ContainerSpec(name="pihole", image="pihole/pihole"))
    assert result.applied is False
    assert "daemon-reload failed" in result.detail


def test_stop_and_remove_stops_and_removes_unit_only():
    runner = FakeRunner(files={quadlet.unit_path("pihole"): "stub content"})
    runner.script_prefix("systemctl", returncode=0, stdout="", stderr="")
    result = quadlet.stop_and_remove(runner, "pihole")
    assert result.applied is True
    assert "image/volumes untouched" in result.detail
    # Deliberately `stop`, never `disable` - see stop_and_remove's own
    # docstring for why `disable` is the wrong verb for a Quadlet unit.
    assert ["systemctl", "stop", "pihole.service"] in runner.calls
    assert not any(call[:2] == ["systemctl", "disable"] for call in runner.calls)
    assert quadlet.unit_path("pihole") not in runner.files


def test_stop_and_remove_reports_failure_and_leaves_unit_in_place():
    runner = FakeRunner(files={quadlet.unit_path("pihole"): "stub content"})
    runner.script(lambda a: a[:2] == ["systemctl", "stop"], FakeProc(1, "", "unit not found"))
    result = quadlet.stop_and_remove(runner, "pihole")
    assert result.applied is False
    assert quadlet.unit_path("pihole") in runner.files


def test_status_returns_systemd_vocabulary_unchanged():
    runner = FakeRunner()
    runner.script_prefix("systemctl", returncode=0, stdout="active\n", stderr="")
    assert quadlet.status(runner, "pihole") == "active"


def test_is_running_true_and_false():
    runner = FakeRunner()
    runner.script_prefix("systemctl", returncode=0, stdout="active\n", stderr="")
    assert quadlet.is_running(runner, "pihole") is True

    runner2 = FakeRunner()
    runner2.script_prefix("systemctl", returncode=3, stdout="inactive\n", stderr="")
    assert quadlet.is_running(runner2, "pihole") is False
