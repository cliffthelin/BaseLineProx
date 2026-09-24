"""Scheduling coverage: system cron directories, /etc/crontab, root's
crontab, explicitly allowlisted service-account crontabs, and systemd
timers. Any *other* user's crontab is recorded as a count plus tokenized
identities only - never a raw username, never its contents (design doc
correction #4)."""
from .status_notes import note as _note, notes as _notes

ALLOWLISTED_SERVICE_ACCOUNTS = ["baseline"]


def _sanitize_cron_line(line, redactor):
    parts = line.split()
    if len(parts) < 6:
        return line  # comment/blank/malformed - not a schedule+command line
    schedule, command_tokens = parts[:5], parts[5:]
    sanitized = []
    for tok in command_tokens:
        if "=" in tok or tok.startswith("/") or tok.startswith("http"):
            sanitized.append(redactor.tokenize(tok, "cron-arg"))
        else:
            sanitized.append(tok)
    return " ".join(schedule) + " " + " ".join(sanitized)


def _sanitize_lines(text, redactor):
    return [
        _sanitize_cron_line(line, redactor)
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def collect_scheduling(runner, redactor):
    etc_crontab = runner.read_text("/etc/crontab")

    cron_dirs = {}
    collection_notes = _notes((etc_crontab, "read /etc/crontab"))
    for d in ("cron.d", "cron.daily", "cron.hourly", "cron.weekly", "cron.monthly"):
        listing = runner.listdir(f"/etc/{d}")
        cron_dirs[d] = listing.stdout.splitlines() if listing.ok else []
        collection_notes += _notes((listing, f"listdir /etc/{d}"))

    root_crontab = runner.run(["crontab", "-l", "-u", "root"])
    collection_notes += _notes((root_crontab, "crontab -l -u root"))

    service_crontabs = {}
    for account in ALLOWLISTED_SERVICE_ACCOUNTS:
        result = runner.run(["crontab", "-l", "-u", account])
        if result.ok:
            service_crontabs[account] = _sanitize_lines(result.stdout, redactor)
        else:
            n = _note(result, f"crontab -l -u {account}")
            if n:
                collection_notes.append(n)

    spool = runner.listdir("/var/spool/cron/crontabs")
    other_user_tokens = []
    if spool.ok:
        names = [
            n for n in spool.stdout.splitlines()
            if n not in ALLOWLISTED_SERVICE_ACCOUNTS and n != "root"
        ]
        other_user_tokens = [redactor.tokenize(n, "user") for n in names]
    else:
        n = _note(spool, "listdir /var/spool/cron/crontabs")
        if n:
            collection_notes.append(n)

    timers = runner.run(["systemctl", "list-timers", "--all"])
    collection_notes += _notes((timers, "systemctl list-timers --all"))

    return {
        "etc_crontab": _sanitize_lines(etc_crontab.stdout, redactor) if etc_crontab.ok else [],
        "system_cron_dirs": cron_dirs,
        "root_crontab": _sanitize_lines(root_crontab.stdout, redactor) if root_crontab.ok else [],
        "allowlisted_service_crontabs": service_crontabs,
        "other_user_crontabs_count": len(other_user_tokens),
        "other_user_crontabs_tokenized": other_user_tokens,
        "systemd_timers": timers.stdout if timers.ok else None,
        "_collection_notes": collection_notes,
    }
