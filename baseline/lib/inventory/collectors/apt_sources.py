"""APT repository sources - both the legacy one-line `.list` format and
the modern Deb822 `.sources` format, fully parsed (not merely detected)
so a comparison can see which channel is actually active. Reading only
`/etc/apt/sources.list` - as this codebase did before this module
existed - can miss the active repositories entirely on a modern
Debian/Proxmox install, where `.sources` files under
`/etc/apt/sources.list.d/` are now the default: a rebuilt host updating
from the wrong channel (enterprise vs no-subscription, or a stale
Debian suite) would look identical to a correct one under the old,
legacy-only collector. That is exactly the drift this module exists to
catch, not paper over.

Every field the two formats can express is preserved (URI, suites,
components, enabled state, Signed-By, architecture restrictions,
source file, and a best-effort channel classification) - nothing is
normalized away. Credentials embedded in a repository URI (a private
mirror with basic auth in the URL) are redacted before anything is
returned; the URI's scheme/host/path/query structure is kept.
"""
import re

from .status_notes import note as _note

_CRED_RE = re.compile(r"://([^/@\s]+)@")


def _redact_uri(uri):
    if not uri:
        return uri
    return _CRED_RE.sub("://[REDACTED]@", uri)


def _channel_for(uri, components):
    haystack = f"{uri or ''} {' '.join(components)}".lower()
    if "no-subscription" in haystack:
        return "no-subscription"
    if "enterprise" in haystack:
        return "enterprise"
    if "pvetest" in haystack or "pve-test" in haystack:
        return "test"
    if "debian.org" in haystack or "ubuntu.com" in haystack:
        return "distro"
    return "unknown"


def _parse_list_line(line, source_file):
    stripped = line.strip()
    enabled = True
    if stripped.startswith("#"):
        enabled = False
        stripped = stripped.lstrip("#").strip()
    if not (stripped.startswith("deb ") or stripped.startswith("deb-src ")):
        return None

    parts = stripped.split()
    type_ = parts[0]
    rest = parts[1:]
    architectures = []
    signed_by = None
    if rest and rest[0].startswith("["):
        joined = " ".join(rest)
        end = joined.find("]")
        if end == -1:
            return None
        opts_str = joined[1:end]
        rest = joined[end + 1:].split()
        for opt in opts_str.split():
            if opt.startswith("arch="):
                architectures = opt[len("arch="):].split(",")
            elif opt.startswith("signed-by="):
                signed_by = opt[len("signed-by="):]

    if len(rest) < 2:
        return None
    uri, suite = rest[0], rest[1]
    components = rest[2:]
    return {
        "source_file": source_file,
        "format": "list",
        "type": type_,
        "enabled": enabled,
        "uri": _redact_uri(uri),
        "suites": [suite],
        "components": components,
        "signed_by": signed_by,
        "architectures": architectures,
        "channel": _channel_for(uri, components),
    }


def parse_list_text(text, source_file):
    entries = []
    for line in text.splitlines():
        entry = _parse_list_line(line, source_file)
        if entry:
            entries.append(entry)
    return entries


def parse_deb822_text(text, source_file):
    """RFC822-style stanzas separated by blank lines; a continuation
    line (leading whitespace) extends the previous field's value -
    matches apt's own Deb822 folding rule closely enough for the
    fields this collector cares about (Types/URIs/Suites/Components/
    Enabled/Signed-By/Architectures are never folded in practice, but
    handling it costs nothing and avoids silently truncating a value
    that is)."""
    entries = []

    def flush(stanza):
        if not stanza:
            return
        types = stanza.get("Types", "deb").split()
        uris = stanza.get("URIs", "").split()
        suites = stanza.get("Suites", "").split()
        components = stanza.get("Components", "").split()
        enabled = stanza.get("Enabled", "yes").strip().lower() not in ("no", "false", "0")
        signed_by = stanza.get("Signed-By")
        architectures = stanza.get("Architectures", "").split()
        for t in types:
            for uri in uris:
                entries.append({
                    "source_file": source_file,
                    "format": "deb822",
                    "type": t,
                    "enabled": enabled,
                    "uri": _redact_uri(uri),
                    "suites": suites,
                    "components": components,
                    "signed_by": signed_by,
                    "architectures": architectures,
                    "channel": _channel_for(uri, components),
                })

    stanza = {}
    current_key = None
    for raw_line in text.splitlines():
        if not raw_line.strip():
            flush(stanza)
            stanza = {}
            current_key = None
            continue
        if raw_line[:1] in (" ", "\t") and current_key:
            stanza[current_key] += " " + raw_line.strip()
            continue
        if raw_line.lstrip().startswith("#"):
            continue
        if ":" in raw_line:
            key, value = raw_line.split(":", 1)
            key = key.strip()
            stanza[key] = value.strip()
            current_key = key
    flush(stanza)
    return entries


def collect(runner):
    entries = []
    collection_notes = []

    legacy = runner.read_text("/etc/apt/sources.list")
    n = _note(legacy, "read /etc/apt/sources.list")
    if n:
        collection_notes.append(n)
    if legacy.ok and legacy.stdout.strip():
        entries += parse_list_text(legacy.stdout, "/etc/apt/sources.list")

    listing = runner.listdir("/etc/apt/sources.list.d")
    n = _note(listing, "listdir /etc/apt/sources.list.d")
    if n:
        collection_notes.append(n)
    names = sorted(listing.stdout.splitlines()) if listing.ok else []

    for name in names:
        if not (name.endswith(".list") or name.endswith(".sources")):
            continue
        path = f"/etc/apt/sources.list.d/{name}"
        content = runner.read_text(path)
        n = _note(content, f"read {path}")
        if n:
            collection_notes.append(n)
        if not content.ok:
            continue
        if name.endswith(".sources"):
            entries += parse_deb822_text(content.stdout, path)
        else:
            entries += parse_list_text(content.stdout, path)

    return {"entries": entries, "_collection_notes": collection_notes}
