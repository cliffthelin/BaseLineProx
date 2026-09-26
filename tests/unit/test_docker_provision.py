"""Unit tests for docker_provision.py - the "compatibility beyond LXC"
utility-service primitive: a Docker image runs identically on a
Proxmox VM, bare metal, or the cloud, unlike pct_provision.py's
Proxmox-native LXC containers. No real docker daemon is ever invoked -
the FakeRunner records every argv and returns scripted results."""
from fake_runner import FakeProc, FakeRunner

import docker_provision as dkr


# -- pure argv builders --------------------------------------------------

def test_create_container_argv_minimal():
    argv = dkr.create_container_argv("util-1", "alpine:3.20")
    assert argv == ["docker", "run", "-d", "--name", "util-1",
                     "--restart", "unless-stopped", "alpine:3.20"]


def test_create_container_argv_with_ports_volumes_and_env():
    argv = dkr.create_container_argv(
        "util-1", "alpine:3.20",
        ports={8080: 80}, volumes={"/srv/util-1": "/data"}, env={"MODE": "prod"},
    )
    assert argv == [
        "docker", "run", "-d", "--name", "util-1", "--restart", "unless-stopped",
        "-p", "8080:80",
        "-v", "/srv/util-1:/data",
        "-e", "MODE=prod",
        "alpine:3.20",
    ]


def test_create_container_argv_foreground_variant():
    argv = dkr.create_container_argv("util-1", "alpine:3.20", detach=False)
    assert "-d" not in argv


def test_start_stop_remove_inspect_argv_shapes():
    assert dkr.start_container_argv("util-1") == ["docker", "start", "util-1"]
    assert dkr.stop_container_argv("util-1") == ["docker", "stop", "util-1"]
    assert dkr.remove_container_argv("util-1") == ["docker", "rm", "-f", "util-1"]
    assert dkr.remove_container_argv("util-1", force=False) == ["docker", "rm", "util-1"]
    assert dkr.inspect_running_argv("util-1") == [
        "docker", "inspect", "util-1", "--format", "{{.State.Running}}",
    ]


# -- Runner-executed operations ------------------------------------------

def test_create_container_reports_success():
    runner = FakeRunner()
    result = dkr.create_container(runner, "util-1", "alpine:3.20")
    assert result.ok is True
    assert runner.calls[0][:4] == ["docker", "run", "-d", "--name"]


def test_create_container_reports_the_real_failure_detail():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["docker", "run"], FakeProc(1, "", "Conflict: container name already in use")),
    ])
    result = dkr.create_container(runner, "util-1", "alpine:3.20")
    assert result.ok is False
    assert "already in use" in result.detail


def test_start_stop_remove_call_docker_directly():
    runner = FakeRunner()
    dkr.start_container(runner, "util-1")
    dkr.stop_container(runner, "util-1")
    dkr.remove_container(runner, "util-1")
    assert runner.calls == [
        ["docker", "start", "util-1"],
        ["docker", "stop", "util-1"],
        ["docker", "rm", "-f", "util-1"],
    ]


def test_is_running_true_when_docker_reports_true():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["docker", "inspect"], FakeProc(0, "true\n", "")),
    ])
    assert dkr.is_running(runner, "util-1") is True


def test_is_running_false_when_docker_reports_false():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["docker", "inspect"], FakeProc(0, "false\n", "")),
    ])
    assert dkr.is_running(runner, "util-1") is False


def test_is_running_false_when_the_container_does_not_exist():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["docker", "inspect"], FakeProc(1, "", "No such object: util-1")),
    ])
    assert dkr.is_running(runner, "util-1") is False
