"""The serial shell driver against a real shell behind a unix socket (a fake console that echoes input like a terminal does)."""
import os
import socket
import subprocess
import threading

import pytest

import serial_shell


class Console:
    """Accepts one connection; echoes what it is sent (as a tty does) and runs each line in a real sh, sending its output back."""

    def __init__(self, path, prompt="user@box:~$ "):
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(path)
        self.server.listen(1)
        self.prompt = prompt
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        conn, _ = self.server.accept()
        conn.settimeout(None)                           # another test may have set a default socket timeout for the whole process
        conn.sendall(self.prompt.encode())
        buf = b""
        while True:
            try:
                chunk = conn.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                done = subprocess.run(["sh", "-c", line.decode()], capture_output=True, text=True)
                conn.sendall(line + b"\r\n" + (done.stdout + done.stderr).replace("\n", "\r\n").encode() + self.prompt.encode())


@pytest.fixture
def shell(tmp_path):
    path = str(tmp_path / "s.sock")
    Console(path)
    s = serial_shell.SerialShell(path, connect_timeout=5)
    yield s
    s.close()


def test_a_command_returns_its_output_and_exit_status_without_the_terminals_echo(shell):
    assert shell.run("echo hello") == (0, "hello")
    status, out = shell.run("echo before; (exit 3)")
    assert status == 3 and "before" in out and "__END_" not in out


def test_a_failing_command_is_reported_not_raised(shell):
    status, out = shell.run("ls /definitely/not/here")
    assert status != 0


def test_a_file_with_awkward_characters_arrives_unchanged(shell, tmp_path):
    data = b"quote ' double \" dollar $HOME backtick ` newline\nline two\n"
    target = tmp_path / "out.txt"
    shell.write_file(str(target), data)
    assert target.read_bytes() == data


def test_a_command_with_a_newline_is_refused(shell):
    with pytest.raises(serial_shell.SerialError):
        shell.run("echo a\necho b")


def test_waiting_for_something_that_never_comes_times_out_and_says_what_it_saw(shell):
    with pytest.raises(serial_shell.SerialError, match="timed out"):
        shell.wait_for(r"never-appears", 1.5)


def test_a_console_that_never_appears_is_reported(tmp_path):
    with pytest.raises(serial_shell.SerialError, match="did not come up"):
        serial_shell.SerialShell(str(tmp_path / "missing.sock"), connect_timeout=1)


def test_waiting_for_a_shell_succeeds_once_one_answers(shell):
    shell.wait_ready(timeout=10)
    assert shell.run("echo after") == (0, "after")


def test_a_login_prompt_is_answered_with_the_given_user_and_password_and_the_wait_goes_on(tmp_path):
    path = str(tmp_path / "login.sock")
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen(1)

    def send(conn, data):
        try:
            conn.sendall(data)
        except OSError:
            pass                                        # the client went away: nothing left to answer

    def serve():
        conn, _ = server.accept()
        conn.settimeout(None)                           # another test may have set a default socket timeout for the whole process
        send(conn, b"box login: ")
        state, buf = "user", b""
        while True:
            try:
                chunk = conn.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode().strip()
                if state == "user":
                    if text == "root":
                        state = "password"
                        send(conn, b"root\r\nPassword: ")
                    else:
                        send(conn, b"Login incorrect\r\n\r\nbox login: ")
                elif state == "password":
                    state = "shell"
                    send(conn, b"\r\n# ")
                elif text.startswith("echo "):
                    send(conn, line + b"\r\n" + text[5:].encode() + b"\r\n# ")
    threading.Thread(target=serve, daemon=True).start()
    s = serial_shell.SerialShell(path, connect_timeout=5)
    s.wait_ready(timeout=60, login=("root", ""))
    s.close()
