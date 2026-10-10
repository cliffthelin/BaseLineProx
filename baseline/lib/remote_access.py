"""Remote-access status for the web app: read-only. What ways in are up (SSH, Tailscale) and what is listening.
It runs a few status commands and changes nothing."""
from __future__ import annotations

_EXPECTED_PORTS = {"22", "8100"}      # SSH and this web app


class RemoteAccessObservationError(ValueError):
    """A successful command returned data that cannot support its status claim."""


def _parse_listening(output):
    if not isinstance(output, str):
        raise RemoteAccessObservationError("invalid ss output: text output unavailable")
    lines = output.splitlines()
    if not lines:
        raise RemoteAccessObservationError("invalid ss output: missing table header")
    header = lines[0].split()
    if (not header or header[0] != "State" or "Local" not in header
            or not any(column.startswith("Address:") for column in header)):
        raise RemoteAccessObservationError("invalid ss output: missing listener table columns")
    listening = []
    for line in lines[1:]:
        if not line.strip():
            continue
        cols = line.split()
        if cols[0] != "LISTEN":
            continue
        if len(cols) < 4:
            raise RemoteAccessObservationError("invalid ss output: incomplete listener row")
        address = cols[3]
        port = address.rsplit(":", 1)[-1]
        if not port:
            raise RemoteAccessObservationError("invalid ss output: listener has no port")
        listening.append({"address": address, "port": port})
    return listening


def _run(runner, argv, errors, *, accepted_returncodes=()):
    try:
        proc = runner.run(argv, timeout=15)
    except Exception as exc:  # noqa: BLE001 - status collection must preserve probe failures
        errors.append(f"{' '.join(argv)}: {type(exc).__name__}: {exc}")
        return None
    if proc.returncode == 0:
        return proc
    if proc.returncode in accepted_returncodes and proc.stdout.strip():
        return proc
    detail = proc.stderr.strip() or proc.stdout.strip() or f"exited {proc.returncode}"
    errors.append(f"{' '.join(argv)}: {detail}")
    return None


def collect(runner) -> dict:
    warnings = []
    errors = []
    ssh = _run(runner, ["systemctl", "is-active", "ssh.socket"], errors,
               accepted_returncodes=(3,))
    ssh_active = None if ssh is None else ssh.stdout.strip() == "active"
    ts_ip = _run(runner, ["tailscale", "ip", "-4"], errors)
    ts_status = _run(runner, ["tailscale", "status"], errors)
    peers = None
    if ts_status is not None:
        lines = [l for l in ts_status.stdout.splitlines() if l.strip()]
        peers = max(len(lines) - 1, 0)
    listening = []
    ss = _run(runner, ["ss", "-ltn"], errors)
    listening_available = ss is not None
    if ss is not None:
        try:
            listening = _parse_listening(ss.stdout)
        except RemoteAccessObservationError as exc:
            errors.append(f"ss -ltn: {exc}")
            listening_available = False
        for item in listening:
            address, port = item["address"], item["port"]
            public = not address.startswith(("127.", "[::1]"))
            if public and port not in _EXPECTED_PORTS and not address.startswith("[::]"):
                warnings.append(f"something is listening on port {port} ({address}) that is neither SSH nor the web app")
    cfg = _run(runner, ["sshd", "-T"], errors)
    if cfg is not None:
        values = dict(l.split(None, 1) for l in cfg.stdout.splitlines() if " " in l)
        if values.get("passwordauthentication", "no").strip() == "yes":
            warnings.append("SSH accepts passwords; key-only login is safer")
        if values.get("permitrootlogin", "no").strip() in ("yes", "without-password", "prohibit-password"):
            if values.get("permitrootlogin", "").strip() == "yes":
                warnings.append("SSH allows direct root login")
    return {"ssh": {"active": ssh_active},
            "tailscale": {"ip": (ts_ip.stdout.strip() if ts_ip else None) or None, "peers": peers},
            "listening": listening, "listening_available": listening_available,
            "observation_errors": errors, "warnings": warnings}
