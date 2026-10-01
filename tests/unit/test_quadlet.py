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


def test_generate_unit_includes_gpu_devices():
    """Decision record 96: gpu_devices takes already-resolved device
    strings (a render node path, or a real CDI identifier) - never a
    raw guess constructed inside generate_unit itself."""
    spec = ContainerSpec(name="llm", image="localhost/llama-server:latest",
                          gpu_devices=["nvidia.com/gpu=GPU-cb3c914b-d388-318f-66b4-4037b4cfa0ce"])
    content = quadlet.generate_unit(spec)
    assert "AddDevice=nvidia.com/gpu=GPU-cb3c914b-d388-318f-66b4-4037b4cfa0ce" in content


def test_generate_unit_includes_a_render_node_device():
    spec = ContainerSpec(name="transcode", image="localhost/ffmpeg:latest",
                          gpu_devices=["/dev/dri/renderD128"])
    content = quadlet.generate_unit(spec)
    assert "AddDevice=/dev/dri/renderD128" in content


def test_generate_unit_supports_multiple_gpu_devices():
    spec = ContainerSpec(name="multi", image="localhost/x:latest",
                          gpu_devices=["/dev/dri/renderD128", "/dev/dri/renderD129"])
    content = quadlet.generate_unit(spec)
    assert "AddDevice=/dev/dri/renderD128" in content
    assert "AddDevice=/dev/dri/renderD129" in content


def test_generate_unit_omits_add_device_when_no_gpu_devices():
    spec = ContainerSpec(name="plain", image="localhost/x:latest")
    content = quadlet.generate_unit(spec)
    assert "AddDevice=" not in content


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


# --------------------------------------------------------------------------
# Rootless mode
# --------------------------------------------------------------------------

def _rootless_runner(uid="1500", home="/home/svc"):
    runner = FakeRunner()
    runner.script_prefix("getent", returncode=0, stdout=f"svc:x:{uid}:{uid}:Service:{home}:/usr/sbin/nologin\n", stderr="")
    runner.script_prefix("podman", returncode=0, stdout="podman version 5.7.0", stderr="")
    runner.script(lambda a: a[:1] == ["runuser"], FakeProc(0, "", ""))
    return runner


def test_unit_path_rootless_requires_user_home():
    import pytest
    with pytest.raises(quadlet.RootlessUserRequired):
        quadlet.unit_path("pihole", rootless=True)


def test_unit_path_rootless_uses_user_home():
    assert quadlet.unit_path("pihole", rootless=True, user_home="/home/svc") == "/home/svc/.config/containers/systemd/pihole.container"


def test_write_and_start_refuses_rootless_without_user():
    runner = FakeRunner()
    runner.script_prefix("podman", returncode=0, stdout="podman version 5.7.0", stderr="")
    spec = ContainerSpec(name="pihole", image="pihole/pihole", rootless=True)
    result = quadlet.write_and_start(runner, spec)
    assert result.applied is False
    assert "requires .user" in result.detail


def test_write_and_start_refuses_when_user_does_not_resolve():
    runner = FakeRunner()
    runner.script_prefix("podman", returncode=0, stdout="podman version 5.7.0", stderr="")
    runner.script_prefix("getent", returncode=2, stdout="", stderr="")
    spec = ContainerSpec(name="pihole", image="pihole/pihole", rootless=True, user="svc")
    result = quadlet.write_and_start(runner, spec)
    assert result.applied is False
    assert "could not resolve user" in result.detail


def test_write_and_start_rootless_writes_to_user_config_and_uses_runuser():
    runner = _rootless_runner(uid="1500", home="/home/svc")
    spec = ContainerSpec(name="pihole", image="pihole/pihole", rootless=True, user="svc")
    result = quadlet.write_and_start(runner, spec)
    assert result.applied is True
    assert "rootless (user=svc)" in result.detail
    assert "/home/svc/.config/containers/systemd/pihole.container" in runner.files
    runuser_calls = [c for c in runner.calls if c[:1] == ["runuser"]]
    assert len(runuser_calls) == 2  # daemon-reload, start
    assert runuser_calls[0][:8] == ["runuser", "-u", "svc", "--", "env", "XDG_RUNTIME_DIR=/run/user/1500", "systemctl", "--user"]
    assert runuser_calls[0][8:] == ["daemon-reload"]
    assert runuser_calls[1][8:] == ["start", "pihole.service"]
    # never touches the root-level unit dir
    assert quadlet.unit_path("pihole") not in runner.files


def test_stop_and_remove_rootless_uses_runuser_and_removes_user_unit():
    runner = _rootless_runner(uid="1500", home="/home/svc")
    runner.files["/home/svc/.config/containers/systemd/pihole.container"] = "stub"
    result = quadlet.stop_and_remove(runner, "pihole", rootless=True, user="svc")
    assert result.applied is True
    assert "/home/svc/.config/containers/systemd/pihole.container" not in runner.files
    runuser_calls = [c for c in runner.calls if c[:1] == ["runuser"]]
    assert runuser_calls[0][8:] == ["stop", "pihole.service"]


def test_status_rootless_uses_runuser():
    runner = FakeRunner()
    runner.script_prefix("getent", returncode=0, stdout="svc:x:1500:1500:Service:/home/svc:/usr/sbin/nologin\n", stderr="")
    runner.script(lambda a: a[:1] == ["runuser"] and a[-2:] == ["is-active", "pihole.service"], FakeProc(0, "active\n", ""))
    assert quadlet.status(runner, "pihole", rootless=True, user="svc") == "active"
    runuser_calls = [c for c in runner.calls if c[:1] == ["runuser"]]
    assert runuser_calls[0][:8] == ["runuser", "-u", "svc", "--", "env", "XDG_RUNTIME_DIR=/run/user/1500", "systemctl", "--user"]


def test_status_rootless_without_user_is_unknown_not_a_crash():
    runner = FakeRunner()
    assert quadlet.status(runner, "pihole", rootless=True, user=None) == "unknown"


def test_a_rootless_unit_targets_default_target_not_multi_user():
    """A rootless unit runs under the user's own systemd instance, which
    has no multi-user.target. Targeting it there made [Install] a no-op
    and the container never started at boot."""
    spec = ContainerSpec(name="caddy", image="quay.io/x/caddy@sha256:ab",
                         rootless=True, user="baseline-app-caddy")
    content = quadlet.generate_unit(spec)
    assert "WantedBy=default.target" in content
    assert "multi-user.target" not in content


def test_a_rootful_unit_still_targets_multi_user():
    content = quadlet.generate_unit(ContainerSpec(name="p", image="i@sha256:ab"))
    assert "WantedBy=multi-user.target" in content


# --- persistence enforcement (v0.2 row 22) -------------------------------

def test_volumes_on_persistent_roots_are_accepted():
    spec = ContainerSpec(name="a", image="x@sha256:1", volumes=[
        "/mnt/APPDATA_PERSONAL/A_C_00001/binds/data:/data",
        "/mnt/USER_ADMIN/state:/state:ro",
        "/mnt/BASELINE/shared:/shared",
        "/var/lib/baseline/guardian:/data",
    ])
    assert quadlet.non_persistent_volumes(spec) == []


def test_volume_on_the_root_filesystem_is_flagged():
    spec = ContainerSpec(name="a", image="x", volumes=["/opt/data:/data"])
    assert quadlet.non_persistent_volumes(spec) == ["/opt/data:/data"]


def test_named_podman_volume_is_flagged_because_it_lives_in_podman_storage():
    spec = ContainerSpec(name="a", image="x", volumes=["mydata:/data"])
    assert quadlet.non_persistent_volumes(spec) == ["mydata:/data"]


def test_volume_on_a_disposable_volume_is_flagged():
    spec = ContainerSpec(name="a", image="x", volumes=[
        "/mnt/SESSION_TEMP/x:/x", "/mnt/INSTALLER_CACHE/y:/y"])
    assert len(quadlet.non_persistent_volumes(spec)) == 2


def test_dotdot_cannot_escape_a_persistent_root():
    spec = ContainerSpec(name="a", image="x", volumes=["/mnt/BASELINE/../../etc:/e"])
    assert quadlet.non_persistent_volumes(spec) == ["/mnt/BASELINE/../../etc:/e"]


def test_prefix_lookalike_is_not_a_persistent_root():
    spec = ContainerSpec(name="a", image="x", volumes=["/mnt/BASELINE_EVIL/x:/x"])
    assert quadlet.non_persistent_volumes(spec) == ["/mnt/BASELINE_EVIL/x:/x"]


def test_no_volumes_means_nothing_to_flag():
    assert quadlet.non_persistent_volumes(ContainerSpec(name="a", image="x")) == []


def test_write_and_start_refuses_a_non_persistent_volume_and_writes_nothing():
    runner = FakeRunner()
    runner.script_prefix("podman", returncode=0, stdout="podman version 5.7.0", stderr="")
    spec = ContainerSpec(name="pihole", image="pihole/pihole", volumes=["/opt/pihole:/etc/pihole"])
    result = quadlet.write_and_start(runner, spec)
    assert result.applied is False
    assert "/opt/pihole:/etc/pihole" in result.detail
    assert runner.writes == []
    assert not any(call[0] == "systemctl" for call in runner.calls)
