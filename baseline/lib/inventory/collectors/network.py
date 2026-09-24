"""Network category: the /etc/network/interfaces closure (structure
only - values redacted) and DNS resolver availability. This redaction
approach mirrors boot/baseline-repair-env-probe.sh's own
redact_interfaces() in spirit, reimplemented locally rather than
imported, since that script lives on a different branch."""
import re

from .status_notes import notes as _notes

_VALUE_LINE_RE = re.compile(r"^(\s*)(address|netmask|gateway|dns-nameservers|dns-search)(\s+).*$")


def _redact_interfaces_text(text):
    out = []
    for line in text.splitlines():
        m = _VALUE_LINE_RE.match(line)
        if m:
            out.append(f"{m.group(1)}{m.group(2)}{m.group(3)}<redacted>")
        else:
            out.append(line)
    return "\n".join(out)


def collect_network(runner):
    interfaces = runner.read_text("/etc/network/interfaces")
    resolvectl_path = runner.which("resolvectl")
    resolv = runner.run(["resolvectl", "status"]) if resolvectl_path else None
    collection_notes = _notes((interfaces, "read /etc/network/interfaces"))
    if resolv is not None:
        collection_notes += _notes((resolv, "resolvectl status"))
    elif not resolvectl_path:
        collection_notes.append({"command": "resolvectl status", "status": "unavailable", "reason": "resolvectl not on PATH"})
    return {
        "interfaces_closure": _redact_interfaces_text(interfaces.stdout) if interfaces.ok else None,
        "dns_available": bool(resolv and resolv.ok),
        "_collection_notes": collection_notes,
    }
