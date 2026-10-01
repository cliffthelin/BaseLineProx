"""Remote-access status for the web app: read-only. What ways in are up (SSH, Tailscale) and what is listening.
It runs a few status commands and changes nothing."""
from __future__ import annotations

_EXPECTED_PORTS = {"22", "8100"}      # SSH and this web app


def _run(runner, argv):
    try:
        proc = runner.run(argv, timeout=15)
    except Exception:  # noqa: BLE001 - a missing tool is a fact to report, not a crash
        return None
    return proc if proc.returncode == 0 else None


def collect(runner) -> dict:
    warnings = []
    ssh = _run(runner, ["systemctl", "is-active", "ssh.socket"])
    ssh_active = None if ssh is None else ssh.stdout.strip() == "active"
    ts_ip = _run(runner, ["tailscale", "ip", "-4"])
    ts_status = _run(runner, ["tailscale", "status"])
    peers = None
    if ts_status is not None:
        lines = [l for l in ts_status.stdout.splitlines() if l.strip()]
        peers = max(len(lines) - 1, 0)
    listening = []
    ss = _run(runner, ["ss", "-ltn"])
    if ss is not None:
        for line in ss.stdout.splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 4 and cols[0] == "LISTEN":
                address = cols[3]
                port = address.rsplit(":", 1)[-1]
                listening.append({"address": address, "port": port})
                public = not address.startswith(("127.", "[::1]"))
                if public and port not in _EXPECTED_PORTS and not address.startswith("[::]"):
                    warnings.append(f"something is listening on port {port} ({address}) that is neither SSH nor the web app")
    cfg = _run(runner, ["sshd", "-T"])
    if cfg is not None:
        values = dict(l.split(None, 1) for l in cfg.stdout.splitlines() if " " in l)
        if values.get("passwordauthentication", "no").strip() == "yes":
            warnings.append("SSH accepts passwords; key-only login is safer")
        if values.get("permitrootlogin", "no").strip() in ("yes", "without-password", "prohibit-password"):
            if values.get("permitrootlogin", "").strip() == "yes":
                warnings.append("SSH allows direct root login")
    return {"ssh": {"active": ssh_active},
            "tailscale": {"ip": (ts_ip.stdout.strip() if ts_ip else None) or None, "peers": peers},
            "listening": listening, "warnings": warnings}
