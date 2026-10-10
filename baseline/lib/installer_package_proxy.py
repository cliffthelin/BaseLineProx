import socket,select,socketserver
class Proxy(socketserver.BaseRequestHandler):
    def handle(self):
        upstream = None
        try:
            self.request.settimeout(30)
            header = b""
            while b"\r\n\r\n" not in header and len(header) < 65536:
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                header += chunk
            first = header.split(b"\r\n", 1)[0].decode()
            method, target, version = first.split()
            from urllib.parse import urlsplit
            if method == "CONNECT":
                host, port = target.rsplit(":", 1)
                port = int(port)
            else:
                parsed = urlsplit(target)
                host, port = parsed.hostname, parsed.port or 80
                relative = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
                header = (f"{method} {relative} {version}".encode() + b"\r\n" + header.split(b"\r\n", 1)[1])
            allowed = host and any(host == d or host.endswith("." + d) for d in (
                "proxmox.com", "nodesource.com", "npmjs.org", "npmjs.com", "ubuntu.com", "canonical.com", "snapcraft.io", "snapcraftcontent.com", "debian.org", "debian.net", "openai.com", "chatgpt.com", "oaistatic.com", "oaiusercontent.com", "claude.ai", "anthropic.com", "claude.com", "spotify.com", "scdn.co", "google.com", "gstatic.com", "vscode.download.prss.microsoft.com", "update.code.visualstudio.com"))
            if not allowed or port not in (80, 443):
                self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                print("PROXY REFUSED", host, port, flush=True)
                return
            upstream = socket.create_connection((host, port), timeout=30)
            if method == "CONNECT":
                self.request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            else:
                upstream.sendall(header)
            print("PROXY", method, host, flush=True)
            while True:
                readable, _, _ = select.select([self.request, upstream], [], [], 60)
                if not readable:
                    return
                for src in readable:
                    data = src.recv(65536)
                    if not data:
                        return
                    (upstream if src is self.request else self.request).sendall(data)
        except (OSError, ValueError) as exc:
            print("PROXY ERROR", type(exc).__name__, str(exc), flush=True)
            return
        finally:
            if upstream:
                upstream.close()

class Server(socketserver.ThreadingTCPServer):
 allow_reuse_address=True
 daemon_threads=True
with Server(("127.0.0.1",32165),Proxy) as server:server.serve_forever()
