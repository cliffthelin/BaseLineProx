"""A minimal QEMU guest-agent client: the same protocol Proxmox's `qm guest exec --pass-stdin` speaks. Used by the OS base builder to look inside a freshly built system (and to tidy it before it is kept)."""
import base64, json, socket, time

class QGA:
    def __init__(self, path, timeout=30):
        self.s = socket.socket(socket.AF_UNIX); self.s.settimeout(timeout); self.s.connect(path); self.buf = b""
    def _read(self):
        while b"\n" not in self.buf:
            chunk = self.s.recv(65536)
            if not chunk: raise EOFError("agent closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line)
    def call(self, command, **args):
        self.s.sendall((json.dumps({"execute": command, "arguments": args}) + "\n").encode())
        while True:
            reply = self._read()
            if reply.get("return") is not None and reply.get("return") == getattr(self, "_sync_id", object()) and command != "guest-sync":
                continue                                    # a late answer to one of the repeated sync requests, not to this call
            break
        if "error" in reply: raise RuntimeError(reply["error"])
        return reply["return"]
    def sync(self, timeout=None):
        """Agree on a message number with the agent. A guest that has not started its agent yet drops what is sent, so the request is repeated every few seconds until it answers; with
        `timeout` (seconds, counted in those repeats) a guest that never answers raises TimeoutError instead of being waited on for ever."""
        attempts = None if timeout is None else max(1, int(timeout // 3))
        n = int(time.time() * 1000) & 0x7fffffff
        self._sync_id = n
        old = self.s.gettimeout()
        self.s.settimeout(3)
        try:
            tried = 0
            while attempts is None or tried < attempts:
                tried += 1
                self.s.sendall((json.dumps({"execute": "guest-sync", "arguments": {"id": n}}) + "\n").encode())
                try:
                    while True:
                        if self._read().get("return") == n:
                            return
                except (socket.timeout, TimeoutError):
                    continue
                except ValueError:
                    continue
            raise TimeoutError("the guest agent did not answer")
        finally:
            self.s.settimeout(old)

    def exec(self, path, args=(), stdin=b"", wait=900, poll=3):
        pid = self.call("guest-exec", path=path, arg=list(args), **({"input-data": base64.b64encode(stdin).decode()} if stdin else {}), **{"capture-output": True})["pid"]
        end = time.time() + wait
        while time.time() < end:
            st = self.call("guest-exec-status", pid=pid)
            if st.get("exited"):
                dec = lambda k: base64.b64decode(st.get(k, "") or "").decode(errors="replace")
                return st.get("exitcode"), dec("out-data"), dec("err-data")
            time.sleep(poll)
        raise TimeoutError("guest command did not finish")
