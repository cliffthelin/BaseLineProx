"""The guest-agent client against a small fake agent on a unix socket: sync, exec with output and exit code, errors, and timeouts."""
import base64
import json
import os
import socket
import threading

import pytest

import qga_client


class FakeAgent:
    def __init__(self, path, script):
        self.path, self.script, self.seen = path, script, []
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(path)
        self.server.listen(1)
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        conn, _ = self.server.accept()
        conn.settimeout(None)                           # another test may have set a default socket timeout for the whole process
        buf = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                request = json.loads(line)
                self.seen.append(request)
                conn.sendall((json.dumps(self.script(request)) + "\n").encode())


def agent(tmp_path, script):
    return FakeAgent(str(tmp_path / "qga.sock"), script)


def test_exec_returns_the_exit_code_and_both_outputs(tmp_path):
    def script(req):
        cmd = req["execute"]
        if cmd == "guest-exec":
            return {"return": {"pid": 7}}
        if cmd == "guest-exec-status":
            return {"return": {"exited": True, "exitcode": 3, "out-data": base64.b64encode(b"hello").decode(), "err-data": base64.b64encode(b"oops").decode()}}
        return {"return": {}}
    fake = agent(tmp_path, script)
    client = qga_client.QGA(fake.path)
    assert client.exec("/bin/true", ["-x"], poll=0) == (3, "hello", "oops")
    first = fake.seen[0]
    assert first["arguments"]["path"] == "/bin/true" and first["arguments"]["arg"] == ["-x"] and first["arguments"]["capture-output"] is True


def test_stdin_goes_to_the_agent_base64_encoded_and_never_as_an_argument(tmp_path):
    def script(req):
        return {"return": {"pid": 1}} if req["execute"] == "guest-exec" else {"return": {"exited": True, "exitcode": 0}}
    fake = agent(tmp_path, script)
    qga_client.QGA(fake.path).exec("/bin/cat", stdin=b"secret", poll=0)
    sent = fake.seen[0]["arguments"]
    assert base64.b64decode(sent["input-data"]) == b"secret" and "secret" not in json.dumps(sent["arg"])


def test_an_agent_error_is_raised_with_its_message(tmp_path):
    fake = agent(tmp_path, lambda req: {"error": {"class": "CommandNotFound", "desc": "no such"}})
    with pytest.raises(RuntimeError, match="CommandNotFound"):
        qga_client.QGA(fake.path).call("guest-nope")


def test_a_command_that_never_finishes_times_out(tmp_path):
    def script(req):
        return {"return": {"pid": 1}} if req["execute"] == "guest-exec" else {"return": {"exited": False}}
    fake = agent(tmp_path, script)
    with pytest.raises(TimeoutError):
        qga_client.QGA(fake.path).exec("/bin/sleep", wait=0.3, poll=0.05)


def test_sync_waits_for_the_echo_of_its_own_number(tmp_path):
    def script(req):
        return {"return": req["arguments"]["id"]}
    fake = agent(tmp_path, script)
    qga_client.QGA(fake.path).sync()
    assert fake.seen[0]["execute"] == "guest-sync"


def test_sync_repeats_its_request_until_a_late_agent_answers(tmp_path):
    seen = []

    def script(req):
        seen.append(req)
        return {"return": req["arguments"]["id"]} if len(seen) >= 3 else None
    path = str(tmp_path / "late.sock")
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen(1)

    def serve():
        conn, _ = server.accept()
        conn.settimeout(None)                           # another test may have set a default socket timeout for the whole process
        buf = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                reply = script(json.loads(line))
                if reply is not None:
                    conn.sendall((json.dumps(reply) + "\n").encode())
    threading.Thread(target=serve, daemon=True).start()
    qga_client.QGA(path).sync(timeout=30)
    assert len(seen) >= 3 and {r["arguments"]["id"] for r in seen} == {seen[0]["arguments"]["id"]}        # the same number each time


def test_sync_gives_up_with_a_timeout_when_the_agent_never_answers(tmp_path):
    fake = agent(tmp_path, lambda req: {"return": "not the number"})
    with pytest.raises(TimeoutError):
        qga_client.QGA(fake.path).sync(timeout=0.5)


def test_a_late_answer_to_a_repeated_sync_does_not_get_mistaken_for_the_next_calls_reply(tmp_path):
    state = {"n": 0}

    def script(req):
        if req["execute"] == "guest-sync":
            state["n"] += 1
            return {"return": req["arguments"]["id"]}
        return {"return": {"pid": 5}}
    fake = agent(tmp_path, script)
    client = qga_client.QGA(fake.path)
    client.sync(timeout=10)
    client.s.sendall((json.dumps({"execute": "guest-sync", "arguments": {"id": client._sync_id}}) + "\n").encode())       # a stray repeat arrives later
    assert client.call("guest-exec", path="/bin/true") == {"pid": 5}
