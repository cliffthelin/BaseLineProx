"""How the Kasm VM is doing, kept as history and turned into suggestions (DR260; operator 2026-10-17).

A probe runs INSIDE the VM through the guest agent and reports plain lines: memory, CPU and disk pressure, failed services, containers that restart or are killed for memory, kernel
driver and firmware errors, and Kasm's own error log lines. Those go into a small SQLite file beside Kasm's own state (APPDATA_ADMIN, WAL, same style as the host sensors store).
What is stored:
  samples          measurements over time (memory available, pressure, disk use ...)
  events           things that went wrong, each with a fingerprint so a repeating error is one thing seen many times, never a flood of rows
  setting_changes  the ACTUAL old and new value of a Kasm server setting, with when; a secret's value is never stored, only that it changed
  launches         how many times each workspace image has been started (Kasm's own accounting), so a build can see what is used
Counts and frequencies are a REPORT computed from these, never a table of their own. `suggestions` is that report: each item names what was seen, what to change and what it buys,
and a suggestion that changes how Baseline builds (drop an image nobody starts) is only ever put to the person.
Nothing here quotes a secret: probe lines are redacted before they are stored or shown.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (ts REAL NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_samples ON samples (metric, ts);
CREATE TABLE IF NOT EXISTS events (ts REAL NOT NULL, source TEXT NOT NULL, severity TEXT NOT NULL, fingerprint TEXT NOT NULL, message TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_events ON events (fingerprint, ts);
CREATE TABLE IF NOT EXISTS setting_changes (ts REAL NOT NULL, name TEXT NOT NULL, old_value TEXT, new_value TEXT, secret INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_changes ON setting_changes (name, ts);
CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS launches (ts REAL NOT NULL, image TEXT NOT NULL, total INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_launches ON launches (image, ts);
"""
DAY = 86400.0
SEVERITIES = ("info", "warning", "error")


def open_db(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


# ---- what runs in the VM -------------------------------------------------------------------------------------------------------------
PROBE = r'''#!/bin/bash
# Read-only. Prints  M <metric> <number>  and  E <severity> <source> <message>  lines. Needs no secret and prints none it can avoid.
mem_total=$(awk '/MemTotal/{print $2}' /proc/meminfo); mem_avail=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
swap_total=$(awk '/SwapTotal/{print $2}' /proc/meminfo); swap_free=$(awk '/SwapFree/{print $2}' /proc/meminfo)
echo "M mem_total_mb $((mem_total/1024))"; echo "M mem_avail_pct $((100*mem_avail/mem_total))"
[ "${swap_total:-0}" -gt 0 ] && echo "M swap_used_pct $((100*(swap_total-swap_free)/swap_total))"
for r in memory cpu io; do
  [ -r /proc/pressure/$r ] && echo "M ${r}_psi_some10 $(awk '/^some/{split($2,a,"="); print a[2]}' /proc/pressure/$r)"
done
cores=$(nproc); echo "M cores $cores"; echo "M load1_per_core $(awk -v c="$cores" '{printf "%.2f", $1/c}' /proc/loadavg)"
for m in / /opt/kasm /mnt/kasm_profiles; do
  mountpoint -q "$m" && echo "M disk_$(echo "$m" | tr '/' '_' | sed 's/^_//; s/^$/root/')_used_pct $(df -P "$m" | awk 'NR==2{gsub("%","",$5); print $5}')"
done
systemctl --failed --no-legend --plain 2>/dev/null | awk '{print "E error service_failed " $1}'
if command -v docker >/dev/null; then
  docker ps -a --format '{{.Names}}' 2>/dev/null | while read -r c; do
    docker inspect --format '{{.Name}} {{.RestartCount}} {{.State.OOMKilled}} {{.State.Status}} {{.State.ExitCode}}' "$c" 2>/dev/null
  done | awk '{n=$1; sub("/","",n); if ($2>0) print "E warning container_restarts " n " restarted " $2 " times"; if ($3=="true") print "E error container_oom " n " was killed for lack of memory"; if ($4=="exited" && $5!=0) print "E warning container_exit " n " exited with code " $5}'
fi
dmesg --level=err,crit,alert,emerg 2>/dev/null | tail -n 60 | sed 's/^\[[ 0-9.]*\] //' | awk '/[Ff]irmware|failed to load|I\/O error|Out of memory|oom-kill|EXT4-fs error|blk_update_request|virtio/{print "E error kernel " $0}'
for f in /opt/kasm/current/log/*_json.log; do
  [ -r "$f" ] && tail -n 400 "$f" 2>/dev/null | grep -E '"levelname": *"(ERROR|CRITICAL)"' | tail -n 20 | sed "s#^#E error kasm:$(basename "$f" _json.log) #"
done
'''

_NAME = r"(?:password|passwd|secret|token|api[_-]?key|authorization|private[_-]?key)"
_REDACT = [(re.compile(r'(?i)("' + _NAME + r'"\s*:\s*")[^"]*(")'), r"\1<redacted>\2"),             # "password": "value" in a JSON line: the value goes, the words stay
           (re.compile(r"(?i)\b(" + _NAME + r")=[^\s&\"',;}]+"), r"\1=<redacted>"),                   # password=value
           (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer <redacted>"),
           (re.compile(r"\b[A-Za-z0-9+/_=-]{28,}\b"), "<redacted>"),                                  # anything that looks like a token or key
           (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*"), "<redacted key>")]


def redact(text: str) -> str:
    for pattern, replacement in _REDACT:
        text = pattern.sub(replacement, text)
    return text


def fingerprint(source: str, message: str) -> str:
    """The same problem with different numbers, ids or times is the same fingerprint."""
    generic = re.sub(r"\b[0-9a-f]{8,}\b|\b\d+(?:\.\d+)?\b|[0-9a-f]{8}-[0-9a-f-]{27}", "#", message.lower())
    return hashlib.sha1(f"{source}|{re.sub(chr(32) + '+', chr(32), generic).strip()}".encode()).hexdigest()[:12]


def _kasm_message(raw: str) -> str:
    """Kasm's structured log line reduced to what happened: the function and the message. Its other fields (request address, user agent, token lifetimes ...) are not kept."""
    import json as _json
    try:
        entry = _json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(entry, dict):
        return raw
    message = entry.get("message", "")
    message = " ".join(str(m) for m in message) if isinstance(message, list) else str(message)
    where = entry.get("funcName") or entry.get("name") or ""
    return f"{where}: {message}".strip(": ").strip()


def parse_probe(output: str) -> tuple:
    """(metrics {name: float}, events [{severity, source, message}]) from the probe's lines; anything else is ignored."""
    metrics, events = {}, []
    for line in output.splitlines():
        parts = line.strip().split(" ", 3)
        if parts[0] == "M" and len(parts) >= 3:
            try:
                metrics[parts[1]] = float(parts[2])
            except ValueError:
                continue
        elif parts[0] == "E" and len(parts) == 4 and parts[1] in SEVERITIES:
            text = _kasm_message(parts[3]) if parts[2].startswith("kasm:") and parts[3].lstrip().startswith("{") else parts[3]
            events.append({"severity": parts[1], "source": parts[2], "message": redact(text[:300])})
    return metrics, events


def record(conn, metrics: dict, events: list, now=None):
    now = time.time() if now is None else now
    conn.executemany("INSERT INTO samples VALUES (?,?,?)", [(now, k, v) for k, v in metrics.items()])
    for event in events:
        conn.execute("INSERT INTO events VALUES (?,?,?,?,?)", (now, event["source"], event["severity"], fingerprint(event["source"], event["message"]), event["message"]))
    conn.commit()


def record_launches(conn, totals: dict, now=None):
    now = time.time() if now is None else now
    conn.executemany("INSERT INTO launches VALUES (?,?,?)", [(now, image, int(n)) for image, n in totals.items()])
    conn.commit()


def record_settings(conn, previous: dict, current: dict, secret_names=(), now=None) -> list:
    """Store a change event, with the real old and new values, for every setting that differs; for a secret only that it changed. Returns what was stored."""
    now = time.time() if now is None else now
    stored = []
    for name, new in current.items():
        old = previous.get(name)
        if name in previous and str(old) == str(new):
            continue
        secret = name in secret_names
        if secret and name in previous and previous[name] == "<secret>":
            continue                                    # a secret is noted once; its value is never seen, so there is nothing to compare
        row = (now, name, None if secret else (None if old is None else str(old)), None if secret else str(new), 1 if secret else 0)
        conn.execute("INSERT INTO setting_changes VALUES (?,?,?,?,?)", row)
        stored.append({"name": name, "old": row[2], "new": row[3], "secret": secret})
    conn.commit()
    return stored


def prune(conn, older_than: float):
    for table in ("samples", "events", "launches"):
        conn.execute(f"DELETE FROM {table} WHERE ts < ?", (older_than,))
    conn.commit()


# ---- Kasm's own records, read the way Kasm offers them --------------------------------------------------------------------------------
# One row per workspace image from Kasm's accounting (a record per session): how many sessions, hours used, and how many ended in a failure. No user name or address is read.
ACCOUNTING_SQL = ("select coalesce(image_friendly_name, image_name, '?'), count(*), coalesce(round(sum(usage_hours)::numeric, 2), 0), "
                  "count(*) filter (where destroy_reason ~* 'fail|error|crash') from accounting group by 1")

# The settings, through Kasm's own admin API (the one its web UI uses), from INSIDE the VM; the admin password arrives on stdin and is never printed. A secret's value is dropped
# in the VM, so it never even reaches the host.
SETTINGS_SCRIPT = r'''#!/bin/bash
# Reads one line (the admin password) from stdin. Prints one JSON array of every setting Kasm reports: name, title, category, description, type, which services a change restarts, its id, whether it is a
# secret, and its value (null for a secret: it never leaves the VM). Kasm's response has no sanitize flag, so a secret is a password-type setting, a name ending in a secret-like word or naming a
# private key, or a value holding PEM private-key material (the same rule as kasm_settings.looks_secret).
set +x
read -r pw
token=$(jq -n --arg p "$pw" '{username:"admin@kasm.local",password:$p,project_id:""}' | curl -sk -X POST https://localhost/api/authenticate -H 'Content-Type: application/json' -d @- | jq -r '.token // empty')
[ -n "$token" ] || exit 3
jq -n --arg t "$token" '{token:$t,username:"admin@kasm.local"}' | curl -sk -X POST https://localhost/api/admin/get_settings -H 'Content-Type: application/json' -d @- \
  | jq -c '[.settings[] | ((.value_type=="password") or (.name|test("(^token$|_token$|_secret$|_password$|_passwd$|private|priv_key$|api_key$|secret_key$)";"i")) or ((.value // "")|tostring|test("-----BEGIN [A-Z ]*PRIVATE KEY-----"))) as $s
            | {name: .name, title: .title, category: .category, description: .description, type: .value_type, restart: .services_restart, id: .setting_id, secret: $s, value: (if $s then null else .value end)}]'
'''

# Changes settings through Kasm's own admin API (update_setting: a setting_id and a value), from inside the VM. stdin: line 1 the admin password, line 2 a JSON array [{id, value}].
# Prints one result line per change. Values come in on stdin, never on a command line, and are never printed.
UPDATE_SETTINGS_SCRIPT = r'''#!/bin/bash
set +x
read -r pw
read -r changes
token=$(jq -n --arg p "$pw" '{username:"admin@kasm.local",password:$p,project_id:""}' | curl -sk -X POST https://localhost/api/authenticate -H 'Content-Type: application/json' -d @- | jq -r '.token // empty')
[ -n "$token" ] || exit 3
echo "$changes" | jq -c '.[]' | while read -r change; do
  reply=$(jq -n --arg t "$token" --argjson c "$change" '{token:$t,username:"admin@kasm.local",setting_id:$c.id,value:$c.value}' | curl -sk -X POST https://localhost/api/admin/update_setting -H 'Content-Type: application/json' -d @-)
  echo "$change" | jq -r '.id' | tr '\n' ' '; echo "$reply" | jq -r 'if .error_message then "error: " + .error_message else "ok" end'
done
'''



def parse_host_view(vm_status: dict, node_status: dict) -> dict:
    """Proxmox's own view of the VM and of the host it runs on, as metrics. Anything missing is simply absent: an older Proxmox has no pressure figures, and that is not an error."""
    out = {}

    def number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    cpu, mem, maxmem = number(vm_status.get("cpu")), number(vm_status.get("mem")), number(vm_status.get("maxmem"))
    if cpu is not None:
        out["host_vm_cpu_pct"] = round(cpu * 100, 1)
    if mem is not None and maxmem:
        out["host_vm_mem_used_pct"] = round(100 * mem / maxmem, 1)
    for kind in ("cpu", "memory", "io"):
        value = number(vm_status.get(f"pressure{kind}some"))
        if value is not None:
            out[f"host_vm_pressure_{kind}"] = value
    node_mem = node_status.get("memory") if isinstance(node_status.get("memory"), dict) else {}
    total, used = number(node_mem.get("total")), number(node_mem.get("used"))
    if total and used is not None:
        out["host_node_mem_used_pct"] = round(100 * used / total, 1)
        out["host_node_mem_total_mb"] = round(total / 1048576)
        out["host_node_mem_free_mb"] = round((total - used) / 1048576)
    swap = node_status.get("swap") if isinstance(node_status.get("swap"), dict) else {}
    swap_total, swap_used = number(swap.get("total")), number(swap.get("used"))
    if swap_total and swap_used is not None:
        out["host_node_swap_used_pct"] = round(100 * swap_used / swap_total, 1)
    node_cpu = number(node_status.get("cpu"))
    if node_cpu is not None:
        out["host_node_cpu_pct"] = round(node_cpu * 100, 1)
    return out


def parse_accounting(output: str) -> list:
    rows = []
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) == 4:
            try:
                rows.append((parts[0].strip(), int(parts[1]), float(parts[2]), int(parts[3])))
            except ValueError:
                continue
    return rows


def record_accounting(conn, rows: list, now=None):
    """Keep each image's running session total, and note a failure only when the total grew since the last look (so a failure is one event, not one per collection)."""
    import json as _json
    now = time.time() if now is None else now
    record_launches(conn, {image: total for image, total, _h, _f in rows}, now=now)
    for image, _total, hours, failures in rows:
        key = f"failed_sessions:{image}"
        previous = conn.execute("SELECT value FROM counters WHERE name=?", (key,)).fetchone()
        if failures and (previous is None or failures > previous[0]):
            grew = failures - (previous[0] if previous else 0)
            conn.execute("INSERT INTO events VALUES (?,?,?,?,?)", (now, "workspace_failed", "warning", fingerprint("workspace_failed", image),
                                                                    f"{image}: {grew} more session(s) ended in a failure ({failures} in all, {hours:g} hours used in all)"))
        conn.execute("INSERT INTO counters VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (key, failures))
    conn.commit()


def parse_settings_full(text: str) -> list:
    """Every setting the settings script reported, as dicts {name, title, category, description, type, restart, id, secret, value}. A second check on the host: whatever the VM said, a setting
    that looks like a secret has its value dropped here too, so a value that should have been withheld never reaches storage or a screen."""
    import json as _json
    import kasm_settings as _ks
    try:
        rows = _json.loads(text.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or "name" not in row:
            continue
        secret = bool(row.get("secret")) or _ks.looks_secret(row["name"], row.get("type") or "", row.get("value"))
        out.append({"name": row["name"], "title": row.get("title") or row["name"], "category": row.get("category") or "", "description": row.get("description") or "",
                    "type": row.get("type") or "string", "restart": [x for x in str(row.get("restart") or "").split(",") if x and x != "None"], "id": row.get("id"),
                    "secret": secret, "value": None if secret or row.get("value") is None else str(row["value"])})
    return out


def parse_settings(text: str) -> tuple:
    """({name: value} for the settings with a value, {names of secrets}) from the settings script's JSON."""
    values, secrets_ = {}, set()
    for row in parse_settings_full(text):
        if row["secret"]:
            secrets_.add(row["name"])
            values[row["name"]] = "<secret>"            # only so that a change of it can be noticed; recorded as a change without a value
        elif row["value"] is not None:
            values[row["name"]] = row["value"]
    return values, secrets_


def latest_settings(conn) -> dict:
    """The last value kept for each setting (a secret shows as the marker), so the next look can tell what changed."""
    latest = {}
    for name, new, secret in conn.execute("SELECT name, new_value, secret FROM setting_changes ORDER BY ts, rowid"):
        latest[name] = "<secret>" if secret else new
    return latest


# ---- reports ---------------------------------------------------------------------------------------------------------------------------
def _values(conn, metric, since):
    return sorted(v for (v,) in conn.execute("SELECT value FROM samples WHERE metric=? AND ts>=?", (metric, since)))


def _percentile(values, q):
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def error_report(conn, since, limit=10) -> list:
    """Repeating problems, most frequent first: what, how many times, first and last seen. (A report computed on demand, not a table of counts.)"""
    rows = conn.execute("SELECT fingerprint, severity, source, MIN(message), COUNT(*), MIN(ts), MAX(ts) FROM events WHERE ts>=? GROUP BY fingerprint ORDER BY COUNT(*) DESC, MAX(ts) DESC LIMIT ?",
                        (since, limit)).fetchall()
    return [{"fingerprint": f, "severity": s, "source": src, "message": m, "count": n, "first": a, "last": b} for f, s, src, m, n, a, b in rows]


def setting_report(conn, since) -> list:
    """The settings that changed, most changed first, WITH their values: (name, times changed, last old value, last new value)."""
    out = []
    for name, n, last in conn.execute("SELECT name, COUNT(*), MAX(ts) FROM setting_changes WHERE ts>=? GROUP BY name ORDER BY COUNT(*) DESC, MAX(ts) DESC", (since,)).fetchall():
        old, new, secret = conn.execute("SELECT old_value, new_value, secret FROM setting_changes WHERE name=? AND ts=? ORDER BY rowid DESC LIMIT 1", (name, last)).fetchone()
        out.append({"name": name, "changes": n, "last_old": old, "last_new": new, "secret": bool(secret), "last": last})
    return out


def launches_report(conn, since) -> dict:
    """Starts per workspace image in the window, from the growth of Kasm's own running total."""
    out = {}
    for (image,) in conn.execute("SELECT DISTINCT image FROM launches").fetchall():
        rows = conn.execute("SELECT total FROM launches WHERE image=? AND ts>=? ORDER BY ts", (image, since)).fetchall()
        before = conn.execute("SELECT total FROM launches WHERE image=? AND ts<? ORDER BY ts DESC LIMIT 1", (image, since)).fetchone()
        base = before[0] if before else (rows[0][0] if rows else 0)
        out[image] = (rows[-1][0] - base) if rows else 0
    return out


def suggestions(conn, vm: dict, now=None, window_days=7) -> list:
    """What to change, why, and what it buys. `vm` is {memory_mb, cpus}. Each item: id, severity, title, evidence, benefit, action (a plain description, never a command that runs itself)."""
    now = time.time() if now is None else now
    since = now - window_days * DAY
    out = []
    mem_avail, mem_psi = _values(conn, "mem_avail_pct", since), _values(conn, "memory_psi_some10", since)
    oom = [e for e in error_report(conn, since, 50) if "oom" in e["fingerprint"] or "lack of memory" in e["message"] or "Out of memory" in e["message"] or "oom-kill" in e["message"]]
    low, stall = _percentile(mem_avail, 0.1), _percentile(mem_psi, 0.9)
    host_used, host_free = _percentile(_values(conn, "host_node_mem_used_pct", since), 0.9), _percentile(_values(conn, "host_node_mem_free_mb", since), 0.1)
    if oom or (low is not None and low < 8) or (stall is not None and stall > 10):
        new = int(vm["memory_mb"] * 1.5) // 512 * 512
        extra = new - vm["memory_mb"]
        evidence = [f"memory available fell to {low:.0f}% at its lowest tenth" if low is not None else "", f"memory stalls reached {stall:.0f}% of the time (90th percentile)" if stall is not None else "",
                    f"{sum(e['count'] for e in oom)} memory kills seen" if oom else ""]
        if host_free is not None and host_free < extra * 1.2:               # the host is the limit: giving the VM more would starve the host
            title = f"The VM needs more memory ({vm['memory_mb']} MB to {new} MB), but the host has only {host_free:.0f} MB free: free memory on the host or add RAM first"
            evidence.append(f"the host's own free memory fell to {host_free:.0f} MB (lowest tenth); the VM would need {extra} MB more")
            action = {"memory_mb": new, "blocked_by_host": True, "host_free_mb": host_free}
            benefit = "the VM stops being killed for memory, without pushing the host into swap"
        else:
            title, action, benefit = f"Give the VM more memory ({vm['memory_mb']} MB to {new} MB)", {"memory_mb": new}, "fewer stalls and no workspace or service killed for lack of memory"
            if host_used is not None:
                evidence.append(f"the host has room: it used at most {host_used:.0f}% of its memory")
        out.append({"id": "more-memory", "severity": "error" if oom else "warning", "title": title, "evidence": evidence, "benefit": benefit, "action": action})
    cpu_psi, load = _values(conn, "cpu_psi_some10", since), _values(conn, "load1_per_core", since)
    cpu_stall, cpu_load = _percentile(cpu_psi, 0.9), _percentile(load, 0.9)
    host_cpu = _percentile(_values(conn, "host_node_cpu_pct", since), 0.9)
    if (cpu_stall is not None and cpu_stall > 20) or (cpu_load is not None and cpu_load > 1.5):
        busy = host_cpu is not None and host_cpu > 90
        out.append({"id": "more-cores", "severity": "warning", "title": f"Give the VM more CPU cores ({vm['cpus']} to {vm['cpus'] + 1})" + (" (the host is busy too)" if busy else ""),
                    "evidence": [f"CPU waiting reached {cpu_stall:.0f}% of the time (90th percentile)" if cpu_stall is not None else "", f"load per core reached {cpu_load:.1f}" if cpu_load is not None else "",
                                 f"the host's own CPUs reached {host_cpu:.0f}% busy, so an extra core will give less than its full share" if busy else ""],
                    "benefit": "sessions respond faster when several are open", "action": {"cpus": vm["cpus"] + 1}})
    swap = _percentile(_values(conn, "host_node_swap_used_pct", since), 0.9)
    if swap is not None and swap >= 20:
        out.append({"id": "host-swapping", "severity": "warning", "title": f"The host is using {swap:.0f}% of its swap",
                    "evidence": [f"host swap use reached {swap:.0f}% (90th percentile)"], "benefit": "less stalling for every VM; the cause is the host running short of memory, not this VM alone",
                    "action": {"investigate": "host memory"}})
    for metric in sorted({m for (m,) in conn.execute("SELECT DISTINCT metric FROM samples WHERE metric LIKE 'disk_%_used_pct'").fetchall()}):
        high = _percentile(_values(conn, metric, since), 0.9)
        if high is not None and high >= 85:
            where = metric[len("disk_"):-len("_used_pct")] or "root"
            out.append({"id": f"disk-{where}", "severity": "error" if high >= 95 else "warning", "title": f"The {where} disk is {high:.0f}% full",
                        "evidence": [f"{metric} reached {high:.0f}%"], "benefit": "room to write; a full disk stops Kasm and loses what is being saved", "action": {"grow_or_clean": where}})
    for item in error_report(conn, since, 20):
        if item["source"] in ("service_failed", "container_oom", "container_exit", "container_restarts", "kernel") or item["source"].startswith("kasm:"):
            if item in oom:
                continue
            what = {"service_failed": "A service in the VM is failing", "container_restarts": "A container keeps restarting", "container_exit": "A container exited with an error",
                    "kernel": "The VM's kernel reports a driver, firmware or storage error"}.get(item["source"], "Kasm logs a repeating error")
            out.append({"id": f"errors-{item['fingerprint']}", "severity": item["severity"], "title": f"{what}: {item['message'][:100]}",
                        "evidence": [f"seen {item['count']} times, first {int((now - item['first']) / 3600)} h ago, last {int((now - item['last']) / 60)} min ago"],
                        "benefit": "fixing the cause removes the repeats and the risk behind them", "action": {"investigate": item["fingerprint"]}})
    starts = launches_report(conn, now - 30 * DAY)
    for image, n in sorted(starts.items()):
        first = conn.execute("SELECT MIN(ts) FROM launches WHERE image=?", (image,)).fetchone()[0]
        if n == 0 and first is not None and first <= now - 30 * DAY:            # watched for the whole 30 days and never started
            out.append({"id": f"unused-{image}", "severity": "info", "title": f"Nobody has started {image} in 30 days",
                        "evidence": [f"0 starts of {image} in the last 30 days"], "benefit": "a smaller base to carry and rebuild if it is left out of the next build",
                        "action": {"recipe": f"drop workspace image {image}", "needs_approval": True}})
    for item in out:
        item["evidence"] = [e for e in item["evidence"] if e]
    order = {"error": 0, "warning": 1, "info": 2}
    return sorted(out, key=lambda s: (order[s["severity"]], s["id"]))
