"""The merged Baseline web app (decision record 83) - one running
server exposing every page `settings_web.py`/`control_panel_web.py`
already had (Settings, Admin, Recovery, Setup, Master Config) plus a
new Drive Administration tab, under one shared navigation bar. Direct
instruction: "merge those two together and add a Drive administration
tab."

Every route here is a thin dispatcher into the already-real, already-
tested `handle_*` functions in `settings_web.py`/`control_panel_web.py`/
`drive_admin.py` - this module reimplements none of their logic, only
composes them under one HTTP server and one nav bar.

**The sudo-password modal (direct instruction: "this application will
never get off the ground if your solution is terminal commands", then
- once an earlier design assumed the process already ran as root -
"if the application wants root then the application is going to have
to ask for it and run it as root")**: every Drive Administration
action is real code this process executes itself, and this process is
**not** required to already be root. Before running an action, the
operator sees a modal describing exactly what will change (the same
description text `drive_admin.ACTIONS` associates with that action -
one source of truth, never a second copy that could drift) and types
their real system password into it. `POST /drive-admin/action` pipes
that password straight to a real `sudo -S`
(`drive_admin.verify_sudo_password` as a cheap preflight, then
`drive_admin.SudoRunner` for the action itself) - the exact identity
check any terminal `sudo` prompt would make, just made by this process
instead of a shell. Never on session/login alone, and never by handing
the operator a script to run in a terminal themselves.
"""
from __future__ import annotations

import html
import hashlib
import http.server
import json
import sqlite3
import os
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse, quote

import control_panel_web as cpw
import drive_admin as da
import drive_installer
import physical_device_safety as pds
import settings_web as sw
import hitl
import operations as ops
import audit_view
import operations_page
import operator_accounts
import remote_access
import vm_host as vh
import vm_page
import workload_jobs
import workload_page
import web_gate as wg
import subprocess
import web_security as ws

from repair import Runner


NAV_TABS = (
    ("/home", "Home"),
    ("/hardware", "Hardware"),
    ("/network", "Network"),
    ("/sensors", "Sensors"),
    ("/vms", "Virtual machines"),
    ("/chat", "Chat"),
    ("/shell", "Console"),
    ("/containers", "Distro containers"),
    ("/environments", "Environments"),
    ("/tools", "Diagnostic tools"),
    ("/ai-setup", "AI providers"),
    ("/vault", "Vault"),
    ("/security", "Two-factor"),
    ("/ceph", "Ceph"),
    ("/settings", "Settings"),
    ("/admin", "Admin"),
    ("/recovery", "Recovery"),
    ("/drive-admin", "Drive Administration"),
    ("/operations", "Operations"),
    ("/operators", "Operators"),
    ("/approvals", "Approvals"),
    ("/audit", "Audit"),
    ("/remote-access", "Remote access"),
    ("/workloads", "Workload jobs"),
    ("/master-config", "Master Config"),
    ("/installation-readiness", "Installation readiness"),
    ("/installer-cache", "Installer Cache"),
    ("/app-isolation", "App Isolation"),
    ("/recipes", "Environment recipes"),
    ("/install-plan", "Installer plan"),
    ("/install-plan?display=desktop", "Installer desktop"),
)


def render_nav(active_path: str) -> str:
    links = "".join(
        f'<a href="{path}" class="{"active" if active_path.startswith(path) else ""}">{label}</a>'
        for path, label in NAV_TABS
    )
    return (f'<nav class="baseline-nav">{links} <a href="/logout">Log out</a>'
            '<form method="post" action="/host/restart" onsubmit="return baselineRequestRestart(event)">'
            '<button type="submit">Restart host</button><span role="status"></span></form></nav>'
            '''<script>
async function baselineRequestRestart(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button');
  const status = form.querySelector('[role="status"]');
  button.disabled = true;
  status.textContent = 'Requesting restart confirmation…';
  try {
    const response = await fetch(form.action, {
      method: 'POST', credentials: 'same-origin', referrerPolicy: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: '{}'
    });
    if (!(response.headers.get('Content-Type') || '').includes('application/json')) {
      throw new Error(await response.text());
    }
    const result = await response.json();
    if (response.status === 401) {
      status.textContent = 'Your login expired. Sign in, then select Restart host again.';
      const link = document.createElement('a'); link.href = '/login'; link.textContent = 'Sign in';
      status.append(' ', link); return;
    }
    status.textContent = result.detail || result.error || 'Restart request failed';
  } catch (error) {
    status.textContent = 'Restart request failed: ' + error.message;
  } finally {
    button.disabled = false;
  }
}
</script>''')


def _with_nav(body_bytes: bytes, active_path: str) -> bytes:
    """Inserts the shared nav bar right after the opening `<body...>`
    tag of an existing rendered page, without touching the already-
    tested render functions that produced it."""
    html = body_bytes.decode()
    shell = '''<style id="baseline-shell-style">
:root{color-scheme:dark}body{background:#0d0e13;color:#e7e9f0;font-family:system-ui,sans-serif}
.baseline-nav{display:flex;flex-wrap:wrap;align-items:center;gap:.6rem 1rem;padding:1rem 0;border-bottom:1px solid #33364a;margin-bottom:1.2rem;font-size:.9rem}
.baseline-nav a{color:#aebddc;text-decoration:none;padding:.3rem 0}
.baseline-nav a.active{color:#fff;border-bottom:2px solid #7fa4ec}
.baseline-nav form{margin:0}.baseline-nav button{margin:0;padding:.4rem .6rem}
button,input,select,textarea{font:inherit;color:#e7e9f0;background:#171923;border:1px solid #33364a;border-radius:5px}
button{cursor:pointer;padding:.4rem .8rem}button:disabled{cursor:default;opacity:.6}
a{color:#9db4ec}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.5rem;border-bottom:1px solid #33364a}
</style>'''
    html = html.replace('</head>', shell + '</head>', 1)
    marker = "<body>"
    idx = html.find(marker)
    if idx == -1:
        return body_bytes
    insert_at = idx + len(marker)
    return (html[:insert_at] + render_nav(active_path) + html[insert_at:]).encode()


_DRIVE_ADMIN_CSS = """
:root { color-scheme: dark; }
html, body { background: #0d0e13; }
body { font-family: -apple-system, system-ui, "Segoe UI", sans-serif; color: #e7e9f0; max-width: 980px; margin: 0 auto; padding: 0 1.5rem 4rem; }
.baseline-nav { display: flex; gap: 1.25rem; padding: 1.25rem 0 1rem; margin-bottom: .5rem; border-bottom: 2px solid #262838; font-size: .95rem; }
.baseline-nav a { color: #9aa0ba; text-decoration: none; padding: .25rem .1rem; }
.baseline-nav a.active { color: #f2f3f8; font-weight: 700; border-bottom: 2px solid #5b7fd4; }
h1 { font-size: 1.5rem; margin: 1.5rem 0 .25rem; letter-spacing: -.01em; }
.subtitle { color: #8890a6; font-size: .92rem; margin: 0 0 1.75rem; }
h2.section-title { font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; color: #8890a6; margin: 2.25rem 0 .9rem; font-weight: 700; }
.drive-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }
.drive-card { display: block; cursor: pointer; background: linear-gradient(180deg, #171923 0%, #14151d 100%); border: 1px solid #262838; border-radius: 12px; padding: 16px 18px; position: relative; overflow: hidden; transition: border-color .12s, background .12s; }
.drive-card:hover { border-color: #3a3d54; }
.drive-card.selected { border-color: #5b7fd4; background: linear-gradient(180deg, #1a2035 0%, #171923 100%); }
.drive-card::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: transparent; }
.drive-card.selected::before { background: #5b7fd4; }
.drive-card input[type="radio"] { position: absolute; top: 14px; right: 14px; margin: 0; accent-color: #5b7fd4; }
.drive-card.acted-on-ok { border-color: #38c98f; box-shadow: 0 0 0 2px rgba(56,201,143,.35); }
.drive-card.acted-on-ok::before { background: #38c98f; }
.drive-card.acted-on-fail { border-color: #d64949; box-shadow: 0 0 0 2px rgba(214,73,73,.35); }
.drive-card.acted-on-fail::before { background: #d64949; }
.acted-on-pill { display: inline-block; float: right; font-size: .68rem; font-weight: 700; padding: 2px 7px; border-radius: 99px; letter-spacing: .03em; background: rgba(255,255,255,.1); color: #cfd2e0; }
.drive-type-pill { display: inline-block; font-size: .72rem; font-weight: 700; padding: 2px 8px; border-radius: 99px; letter-spacing: .03em; background: rgba(91,127,212,.18); color: #9db4ec; margin-bottom: 8px; }
.baseline-pill { display: inline-block; margin-left: 6px; font-size: .72rem; font-weight: 700; padding: 2px 8px; border-radius: 99px; letter-spacing: .03em; background: rgba(56,201,143,.18); color: #6fe3b4; margin-bottom: 8px; }
.drive-group-title { font-size: .8rem; text-transform: uppercase; letter-spacing: .07em; color: #7d84a0; margin: 18px 0 8px; }
.detail-row.missing-row span:last-child { color: #e59a9a; }
.drive-card .drive-name { font-weight: 700; font-size: .96rem; margin-bottom: 2px; padding-right: 20px; }
.drive-card .drive-path { font-family: ui-monospace, "SF Mono", Menlo, monospace; color: #7d84a0; font-size: .82rem; margin-bottom: 10px; }
.drive-card .detail-row { display: flex; justify-content: space-between; font-size: .82rem; padding: 3px 0; border-top: 1px solid #21232f; margin-top: 8px; }
.drive-card .detail-row span:first-child { color: #7d84a0; }
.drive-card .detail-row span:last-child { font-family: ui-monospace, monospace; }
.volume-table { width: 100%; border-collapse: collapse; background: #14151d; border: 1px solid #262838; border-radius: 10px; overflow: hidden; }
.volume-table th { text-align: left; font-size: .72rem; text-transform: uppercase; letter-spacing: .06em; color: #7d84a0; padding: 9px 14px; background: #1a1c27; }
.volume-table td { padding: 9px 14px; font-size: .87rem; border-top: 1px solid #21232f; }
.volume-table td.mono { font-family: ui-monospace, monospace; color: #b9bdd4; }
.volume-table tr.volume-row { cursor: pointer; }
.volume-table tr.volume-row:hover { background: #1a1c27; }
.volume-table tr.volume-detail-row td { background: #10111a; color: #9aa0ba; font-size: .82rem; }
.empty-note { color: #7d84a0; font-size: .87rem; padding: 10px 2px; }
.action-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
.action-card { background: #14151d; border: 1px solid #262838; border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.action-card[hidden] { display: none; }
.action-card.danger { border-color: #4a2130; background: linear-gradient(180deg, #1b1218 0%, #14151d 60%); }
.action-card .action-id { font-family: ui-monospace, monospace; font-size: .78rem; color: #7d84a0; }
.action-card .action-desc { font-size: .87rem; line-height: 1.4; color: #ccd0e0; flex-grow: 1; }
.action-card button { margin-top: 0; width: 100%; background: #2a4d8f; }
.action-card.danger button { background: #a63333; }
.notice { background: #1a2233; border: 1px solid #2f4573; color: #cfe0ff; padding: .6rem .9rem; border-radius: 8px; font-size: .88rem; margin: 1rem 0; }
.action-banner { font-size: 1.05rem; font-weight: 700; padding: 16px 20px; border-radius: 10px; margin: 1.25rem 0 1.5rem; display: flex; align-items: center; gap: 10px; }
.action-banner.ok { background: rgba(56,201,143,.16); border: 2px solid #38c98f; color: #6ee8bb; }
.action-banner.fail { background: rgba(214,73,73,.16); border: 2px solid #d64949; color: #ff9d9d; }
#driveAdminModal { position: fixed; inset: 0; background: rgba(6,7,12,.72); display: none; align-items: center; justify-content: center; z-index: 50; }
#driveAdminModal.open { display: flex; }
#driveAdminModal .box { background: #171923; border: 1px solid #2c2f42; color: #e7e9f0; padding: 26px 28px; border-radius: 14px; width: 420px; box-shadow: 0 20px 60px rgba(0,0,0,.5); }
#driveAdminModal h3 { margin: 0 0 4px; font-size: 1.05rem; }
#driveAdminModal p#driveAdminModalDescription { color: #ccd0e0; font-size: .88rem; line-height: 1.5; margin: 10px 0 16px; padding: 10px 12px; background: #1e2130; border-left: 3px solid #5b7fd4; border-radius: 6px; }
#driveAdminModal label { display: block; font-size: .82rem; color: #9aa0ba; margin: 10px 0 4px; }
#driveAdminModal input { width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 6px; border: 1px solid #33364a; background: #0f1017; color: #e7e9f0; }
#driveAdminModal .modal-actions { display: flex; gap: 10px; margin-top: 18px; }
#driveAdminModal .modal-actions button { flex: 1; margin-top: 0; }
#driveAdminModalCancel { background: #262838; }
#driveAdminModal details.overrides { margin-top: 16px; border-top: 1px solid #2c2f42; padding-top: 10px; }
#driveAdminModal details.overrides summary { cursor: pointer; font-size: .8rem; color: #8890a6; text-transform: uppercase; letter-spacing: .04em; }
#driveAdminModal details.overrides label { margin-top: 10px; }
#driveAdminModal .hint { margin-top: 10px; }
.modal-console { margin-top: 12px; max-height: 220px; overflow-y: auto; background: #0a0b10; border: 1px solid #262838; border-radius: 8px; padding: 10px 12px; font-family: ui-monospace, monospace; font-size: .78rem; line-height: 1.5; color: #9dd6a0; white-space: pre-wrap; }
.modal-console[hidden] { display: none; }
.screendump-box { background: #0a0b10; border: 1px solid #262838; border-radius: 8px; padding: 12px; margin-bottom: 20px; }
.screendump-box img { max-width: 100%; display: block; border-radius: 4px; margin-bottom: 10px; }
.screendump-box img[hidden] { display: none; }
.hw-table { width: 100%; border-collapse: collapse; background: #14151d; border: 1px solid #262838; border-radius: 10px; overflow: hidden; margin: 12px 0; }
.hw-table th { text-align: left; font-size: .72rem; text-transform: uppercase; letter-spacing: .06em; color: #7d84a0; padding: 10px 14px; background: #1a1c27; }
.hw-table td { padding: 10px 14px; font-size: .87rem; border-top: 1px solid #21232f; color: #ccd0e0; }
.hw-table strong { color: #e7e9f0; }
"""


def render_drive_admin_page(*, drives: list, volumes: list, actions: list, notice: str = "",
                             notice_ok: bool | None = None, acted_on_path: str | None = None,
                             daily_ok: bool = False, selected_serial: str = "",
                             volume_error: str = "", drive_error: str = "") -> bytes:
    """`notice_ok`: `True` (real success), `False` (real refusal/
    failure), or `None` (no action just ran - e.g. a plain page load).
    A prior version rendered every notice with the same quiet blue
    styling that blended into the dark page - a real rebuild had
    genuinely succeeded and the operator couldn't tell (direct
    feedback: "it took me back to previous screen and nothing
    happened" - something *had* happened, the banner just failed to
    say so clearly). Success and failure now get visibly distinct,
    impossible-to-miss banners instead of one generic one.

    `acted_on_path`: the real device path a just-completed action
    targeted (threaded through from the modal's own device select, via
    the real redirect after `/drive-admin/action` returns), so *that*
    specific card can be marked - direct feedback: the page showed a
    real failure banner but gave no visual link to which of a dozen
    drive cards it was actually about."""
    if not notice:
        notice_html = ""
    elif notice_ok is True:
        notice_html = f'<div class="action-banner ok">&#10003; {html.escape(notice, quote=False)}</div>'
    elif notice_ok is False:
        notice_html = f'<div class="action-banner fail">&#10007; {html.escape(notice, quote=False)}</div>'
    else:
        notice_html = f'<p class="notice">{html.escape(notice, quote=False)}</p>'

    if drives:
        # A radio group can only ever have ONE genuinely checked option
        # - more than one candidate can carry is_default (this project's
        # own two pre-authorized drives both do), so only the first one
        # in list order is actually pre-selected; marking every
        # is_default card as visually "selected" would lie about which
        # one the browser really checks.
        default_path = next((d["path"] for d in drives if d.get("is_default")), drives[0]["path"])
        if selected_serial:
            default_path = next((d['path'] for d in drives if d.get('serial') == selected_serial), None)
            if default_path is None:
                notice_html += '<p role="alert">The requested drive is no longer available or eligible. No other drive has been selected.</p>'


        def _drive_card(d: dict) -> str:
            missing = d.get("missing_baseline_volumes") or []
            baseline_pill = '<span class="baseline-pill">Baseline drive</span>' if d.get("is_baseline_drive") else ""
            missing_html = (
                f'<div class="detail-row missing-row"><span>Missing</span><span>{", ".join(missing)}</span></div>'
                if missing else "")
            return f"""
<label class="drive-card {'selected' if d['path'] == default_path else ''} {'acted-on-ok' if d['path'] == acted_on_path and notice_ok is True else ''} {'acted-on-fail' if d['path'] == acted_on_path and notice_ok is False else ''}">
  <input type="radio" name="targetDrive" value="{d['path']}" {"checked" if d['path'] == default_path else ""}>
  <span class="drive-type-pill">{d.get('drive_type', 'Other')}</span>
  {baseline_pill}
  {'<span class="acted-on-pill">last action</span>' if d['path'] == acted_on_path and notice_ok is not None else ''}
  <div class="drive-name">{d.get('model', 'Unknown model')}</div>
  <div class="drive-path">{d['path']}</div>
  <div class="detail-row"><span>Serial</span><span>{html.escape(d.get('serial') or 'not reported')}</span></div>
  <div class="detail-row"><span>Size</span><span>{d.get('size', '—')}</span></div>
  <div class="detail-row"><span>Partitions</span><span>{d.get('partition_count') if d.get('partition_count') is not None else '—'}</span></div>
  <div class="detail-row"><span>Data</span><span>{d.get('usage_text', 'unknown')}</span></div>
  {missing_html}
</label>"""

        # Direct instruction, 2026-09-29: any real Baseline-installed
        # drive is grouped at the top under its own heading - the list
        # itself already arrives pre-sorted (drive_admin.list_candidate_
        # drives), this just draws the group boundary.
        baseline_drives = [d for d in drives if d.get("is_baseline_drive")]
        other_drives = [d for d in drives if not d.get("is_baseline_drive")]
        drive_cards = ""
        if baseline_drives:
            drive_cards += '<h3 class="drive-group-title">Baseline Installed</h3><div class="drive-grid">'
            drive_cards += "".join(_drive_card(d) for d in baseline_drives)
            drive_cards += "</div>"
        if other_drives:
            if baseline_drives:
                drive_cards += '<h3 class="drive-group-title">Other Drives</h3>'
            drive_cards += '<div class="drive-grid">' + "".join(_drive_card(d) for d in other_drives) + "</div>"
    elif drive_error:
        drive_cards = ('<p class="empty-note"><strong>Drive inventory failed:</strong> '
                       + html.escape(drive_error, quote=False) + '</p>')
    else:
        drive_cards = '<p class="empty-note">No eligible drives were found.</p>'

    if volume_error:
        volumes_html = ('<p class="empty-note"><strong>Volume inventory failed:</strong> '
                        + html.escape(volume_error, quote=False) + '</p>')
    elif volumes:
        def _usage_text(v: dict) -> str:
            if v.get("total_bytes") and v.get("used_bytes") is not None:
                pct = v.get("percent_used") or 0
                return f"{da._format_bytes(v['used_bytes'])} used of {da._format_bytes(v['total_bytes'])} ({pct:.0f}%)"
            return "not mounted"

        def _lv_text(v: dict) -> str:
            if v.get("lv_exists"):
                size = da._format_bytes(v["lv_size_bytes"]) if v.get("lv_size_bytes") else "unknown size"
                return f"{v['lv_name']} - {size} allocated"
            return f"{v['lv_name']} - not created yet"

        def _update_checkbox(v: dict) -> str:
            label = html.escape(str(v["label"]), quote=True)
            if v["label"] == "INSTALLER_CACHE":
                return f'<input type="checkbox" class="volume-select" value="{label}">'
            return (f'<input type="checkbox" class="volume-select" value="{label}" disabled '
                    'title="Only INSTALLER_CACHE stores updateable Debian package artifacts">')

        volume_rows = "".join(f"""
<tr class="volume-row" data-volume-idx="{i}">
  <td>{_update_checkbox(v)}</td>
  <td>{v['label']}</td><td class="mono">{v['mountpoint']}</td><td class="mono">{_usage_text(v)}</td>
</tr>
<tr class="volume-detail-row" data-volume-idx="{i}" hidden>
  <td></td><td colspan="3" class="mono">Partition (LVM logical volume): {_lv_text(v)}</td>
</tr>""" for i, v in enumerate(volumes))
        volumes_html = f"""<table class="volume-table">
<tr><th><input type="checkbox" id="volumeSelectAll"></th><th>Volume</th><th>Mountpoint</th><th>Used</th></tr>{volume_rows}</table>
<p class="hint">Click a row to see its real partition (LVM logical volume) name and allocated size.</p>"""
    else:
        volumes_html = '<p class="empty-note">No volume records were returned.</p>'

    action_cards = "".join(f"""
<div class="action-card {'danger' if 'PERMANENTLY ERASE' in a['description'] else ''}" data-action-card-id="{a['action_id']}"
     {'hidden' if a['action_id'] == 'update_selected' else ''}>
  <div class="action-id">{a['action_id']}</div>
  <div class="action-desc">{a['description']}</div>
  <button type="button" class="drive-admin-action" data-action-id="{a['action_id']}" data-description="{a['description']}">Run&hellip;</button>
</div>""" for a in actions if a['action_id'] != 'update_installed_drive')
    action_cards += '<p><a href="/install-plan">Review and update an existing installation</a></p>'

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Drive Administration</title><style>{_DRIVE_ADMIN_CSS}</style></head>
<body>
<h1>Drive Administration</h1>
<p class="subtitle">Every real, non-boot drive attached to this machine. The pre-authorized drive is selected by default - pick any other to target it instead.</p>
{notice_html}

<h2 class="section-title">Physical drives</h2>
{drive_cards}

<h2 class="section-title">Volumes</h2>
<p class="subtitle">Select INSTALLER_CACHE to refresh newer Debian package archives. Other volumes hold the operating system or user data and are not package caches. Update only appears when a Baseline drive is selected above.</p>
{volumes_html}

<h2 class="section-title">Live install screen</h2>
<p class="subtitle">Real, current screen of any install running right now (build_self_installer) - click Refresh, never auto-polling, so it never hammers a real QEMU process.</p>
<div class="screendump-box">
  <img id="screendumpImg" hidden>
  <p id="screendumpEmpty" class="empty-note">No active install found, or Refresh hasn't been clicked yet.</p>
  <button type="button" id="screendumpRefresh">Refresh</button>
</div>

<h2 class="section-title">Actions</h2>
<div class="action-grid">{action_cards}</div>

<div id="driveAdminModal">
  <div class="box">
    <h3>Confirm this change</h3>
    <p id="driveAdminModalDescription"></p>
    <div id="driveAdminModalParams"></div>
    <div class="modal-actions">
      <button type="button" id="driveAdminModalConfirm">Authorize and run</button>
      <button type="button" id="driveAdminModalCancel">Cancel</button>
    </div>
    <p class="hint">Runs immediately on confirm - a real native system dialog will ask for your password separately (PolicyKit), never typed into this page.</p>
    <pre id="driveAdminModalConsole" class="modal-console" hidden></pre>
  </div>
</div>

<script id="driveAdminDriveData" type="application/json">{json.dumps(drives)}</script>
<script id="driveAdminActionData" type="application/json">{json.dumps({a["action_id"]: bool(a.get("requires_device")) for a in actions})}</script>
<script>
const driveList = JSON.parse(document.getElementById("driveAdminDriveData").textContent);
const requiresDeviceById = JSON.parse(document.getElementById("driveAdminActionData").textContent);

function updateActionVisibilityForSelectedDrive() {{
  const path = currentlySelectedDrivePath();
  const drive = driveList.find(d => d.path === path);
  const updateCard = document.querySelector('[data-action-card-id="update_selected"]');
  if (updateCard) updateCard.hidden = !(drive && drive.is_baseline_drive);
}}

document.querySelectorAll('input[name="targetDrive"]').forEach(radio => {{
  radio.addEventListener("change", () => {{
    document.querySelectorAll(".drive-card").forEach(card => card.classList.remove("selected"));
    radio.closest(".drive-card").classList.add("selected");
    updateActionVisibilityForSelectedDrive();
  }});
}});
updateActionVisibilityForSelectedDrive();

document.querySelectorAll(".volume-row").forEach(row => {{
  row.addEventListener("click", (e) => {{
    if (e.target.tagName === "INPUT") return;
    const idx = row.dataset.volumeIdx;
    const detail = document.querySelector(`.volume-detail-row[data-volume-idx="${{idx}}"]`);
    if (detail) detail.hidden = !detail.hidden;
  }});
}});

const volumeSelectAll = document.getElementById("volumeSelectAll");
if (volumeSelectAll) {{
  volumeSelectAll.addEventListener("change", () => {{
    document.querySelectorAll(".volume-select:not(:disabled)").forEach(cb => {{ cb.checked = volumeSelectAll.checked; }});
  }});
}}

document.getElementById("screendumpRefresh").addEventListener("click", async () => {{
  const img = document.getElementById("screendumpImg");
  const empty = document.getElementById("screendumpEmpty");
  const res = await fetch("/drive-admin/screendump?workspace=" + encodeURIComponent("/var/tmp/baseline-self-installer") + "&t=" + Date.now());
  if (!res.ok) {{
    img.hidden = true;
    empty.hidden = false;
    const body = await res.json().catch(() => ({{}}));
    empty.textContent = body.error || "No active install found.";
    return;
  }}
  const blob = await res.blob();
  img.src = URL.createObjectURL(blob);
  img.hidden = false;
  empty.hidden = true;
}});

function currentlySelectedDrivePath() {{
  const checked = document.querySelector('input[name="targetDrive"]:checked');
  return checked ? checked.value : (driveList[0] ? driveList[0].path : "");
}}

function deviceSelectHtml(selectedPath) {{
  const options = driveList.map(d =>
    `<option value="${{d.path}}" ${{d.path === selectedPath ? "selected" : ""}}>${{d.path}} - ${{d.drive_type}} - ${{d.model}} (${{d.size}})</option>`
  ).join("");
  return `<label>Target drive (not locked to the default - pick any listed drive)
    <select id="paramDevicePath">${{options}}</select></label>`;
}}

function selectedVolumeLabels() {{
  return Array.from(document.querySelectorAll(".volume-select:checked:not(:disabled)")).map(cb => cb.value);
}}

// Technical override fields - direct instruction: "should not be
// invisible to a technician/developer but they should be hidden away
// in an override tab" - a real, always-present <details> disclosure,
// collapsed by default so the primary flow stays "pick a drive and
// click", but never removed or buried behind a separate permission.
// Every value here is optional; leaving a field blank means "let
// self_installer.py auto-derive/generate/locate it, same as if this
// section didn't exist at all."
const SELF_INSTALLER_OVERRIDE_FIELDS = [
  {{id: "paramExpectedSerial", param: "expected_serial", label: "Expected drive serial", placeholder: "auto-read from the selected drive"}},
  {{id: "paramProxmoxSourceIso", param: "proxmox_source_iso", label: "Proxmox source ISO path", placeholder: "auto-located in INSTALLER_CACHE"}},
  {{id: "paramServerHost", param: "server_host", label: "Answer-server host", placeholder: "10.0.2.2 (QEMU gateway)"}},
  {{id: "paramCertPath", param: "cert_path", label: "TLS certificate path", placeholder: "auto-generated"}},
  {{id: "paramKeyPath", param: "key_path", label: "TLS key path", placeholder: "auto-generated"}},
  {{id: "paramTargetMac", param: "target_mac", label: "Target MAC address", placeholder: "none"}},
  {{id: "paramTargetDmiProduct", param: "target_dmi_product", label: "Target DMI product string", placeholder: "none"}},
];

function overridesHtml() {{
  const fields = SELF_INSTALLER_OVERRIDE_FIELDS.map(f =>
    `<label>${{f.label}} <input id="${{f.id}}" placeholder="${{f.placeholder}}"></label>`
  ).join("");
  return `<details class="overrides">
    <summary>Overrides (technical - leave blank to auto-detect)</summary>
    ${{fields}}
  </details>`;
}}

function updateSelectedParamsHtml() {{
  const selected = selectedVolumeLabels();
  const selectedText = selected.length ? "INSTALLER_CACHE" : "(select INSTALLER_CACHE above)";
  return `<p>Refresh newer Debian package archives in: ${{selectedText}}</p><p class="hint">APT verifies downloads using the host's configured repository trust policy. Packages are added to the cache; they are not installed on this host.</p>`;
}}

function mountVolumeParamsHtml() {{
  return `<label>Logical volume name (as it exists in the drive's real volume group)
      <input id="paramLvName" value="root"></label>
    <label>Mountpoint (leave blank for the default: /mnt/&lt;vg&gt;-&lt;lv&gt;-inspect)
      <input id="paramMountpoint" placeholder="/mnt/pve-root-inspect"></label>`;
}}

function partitionUnmountParamsHtml() {{
  return `<label>Mounted partition location
      <input id="paramPartitionMountpoint" value="/mnt/sdb2" autocomplete="off"></label>
    <p class="muted">The app checks that this mount belongs to the selected drive before unmounting it.</p>`;
}}

let pendingActionId = null;
document.querySelectorAll(".drive-admin-action").forEach(btn => {{
  btn.addEventListener("click", () => {{
    pendingActionId = btn.dataset.actionId;
    document.getElementById("driveAdminModalDescription").textContent = btn.dataset.description;
    let extra = "";
    if (pendingActionId === "build_self_installer") extra = overridesHtml();
    else if (pendingActionId === "update_selected") extra = updateSelectedParamsHtml();
    else if (pendingActionId === "mount_volume" || pendingActionId === "unmount_volume") extra = mountVolumeParamsHtml();
    else if (pendingActionId === "unmount_partition") extra = partitionUnmountParamsHtml();
    document.getElementById("driveAdminModalParams").innerHTML =
      requiresDeviceById[pendingActionId]
        ? deviceSelectHtml(currentlySelectedDrivePath()) + extra
        : extra;
    const consoleEl = document.getElementById("driveAdminModalConsole");
    consoleEl.textContent = "";
    consoleEl.hidden = true;
    document.getElementById("driveAdminModal").classList.add("open");
  }});
}});
document.getElementById("driveAdminModalCancel").addEventListener("click", () => {{
  document.getElementById("driveAdminModal").classList.remove("open");
}});
function sleep(ms) {{ return new Promise(r => setTimeout(r, ms)); }}

async function pollJobLog(jobId, consoleEl) {{
  let shown = 0;
  while (true) {{
    let job;
    try {{
      const res = await fetch("/drive-admin/job-log?job_id=" + encodeURIComponent(jobId));
      job = await res.json();
    }} catch (e) {{
      consoleEl.textContent += "\\n(lost contact with the server while polling for progress)";
      return {{outcome: "error", detail: "lost contact with the server while polling for progress"}};
    }}
    if (job.lines && job.lines.length > shown) {{
      for (let i = shown; i < job.lines.length; i++) consoleEl.textContent += job.lines[i] + "\\n";
      shown = job.lines.length;
      consoleEl.scrollTop = consoleEl.scrollHeight;
    }}
    if (job.done) return job;
    await sleep(700);
  }}
}}

// A drive action never runs on request: a person must confirm that exact request, each time, by typing the
// phrase shown and entering this machine's root password or passphrase. Everything is added with textContent.
const DAILY_OK = {"true" if daily_ok else "false"};
function askForNativePolicyKit(challenge) {{
  return new Promise((resolve) => {{
    const box=document.createElement("div"); box.id="hitlBox";
    const summary=document.createElement("pre"); summary.textContent=challenge.summary;
    const lead=document.createElement("p"); lead.textContent="Continue to the Ubuntu permission prompt. The action runs only if PolicyKit authorizes it.";
    const msg=document.createElement("p"); msg.id="hitlMsg";
    const ok=document.createElement("button"); ok.type="button"; ok.disabled=true;
    const cancel=document.createElement("button"); cancel.type="button"; cancel.textContent="Cancel";
    let wait=challenge.min_wait; ok.textContent="Continue ("+wait+")";
    const timer=setInterval(()=>{{wait-=1;if(wait<=0){{clearInterval(timer);ok.disabled=false;ok.textContent="Continue to Ubuntu prompt";}}else ok.textContent="Continue ("+wait+")";}},1000);
    ok.addEventListener("click",async()=>{{
      ok.disabled=true;
      const res=await fetch("/drive-admin/execute-native",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{challenge_id:challenge.id}})}});
      const body=await res.json();
      if(body.job_id){{clearInterval(timer);box.remove();resolve(body);}}
      else{{msg.textContent=body.detail||body.error||"PolicyKit action was refused.";ok.disabled=false;}}
    }});
    cancel.addEventListener("click",()=>{{clearInterval(timer);box.remove();resolve({{detail:"Cancelled: nothing was run."}});}});
    box.append(summary,lead,msg,ok,cancel); (document.querySelector("#driveAdminModal .modal-body")||document.getElementById("driveAdminModal")).appendChild(box);
  }});
}}

function askForConfirmation(challenge) {{
  if (pendingActionId === "unmount_partition") return askForNativePolicyKit(challenge);
  return new Promise((resolve) => {{
    const modal = document.getElementById("driveAdminModal");
    const box = document.createElement("div");
    box.id = "hitlBox";
    const summary = document.createElement("pre");
    summary.textContent = challenge.summary;
    const lead = document.createElement("p");
    lead.textContent = "A person must confirm this. Type exactly: " + challenge.phrase;
    const typed = document.createElement("input");
    typed.id = "hitlTyped";
    typed.autocomplete = "off";
    typed.placeholder = challenge.phrase;
    const secret = document.createElement("input");
    secret.id = "hitlSecret";
    secret.type = "password";
    secret.autocomplete = "off";
    secret.placeholder = "This machine's root password or passphrase";
    const msg = document.createElement("p");
    msg.id = "hitlMsg";
    const ok = document.createElement("button");
    ok.type = "button";
    ok.disabled = true;
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "Cancel";
    let wait = challenge.min_wait;
    ok.textContent = "Confirm (" + wait + ")";
    const timer = setInterval(() => {{
      wait -= 1;
      if (wait <= 0) {{ clearInterval(timer); ok.disabled = false; ok.textContent = "Confirm"; }}
      else {{ ok.textContent = "Confirm (" + wait + ")"; }}
    }}, 1000);
    ok.addEventListener("click", async () => {{
      ok.disabled = true;
      const res = await fetch("/drive-admin/confirm", {{
        method: "POST", headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{challenge_id: challenge.id, typed: typed.value, secret: secret.value,
          daily: DAILY_OK && daily.checked}}),
      }});
      const body = await res.json();
      secret.value = "";
      if (body.job_id) {{ clearInterval(timer); box.remove(); resolve(body); }}
      else {{ msg.textContent = body.detail || "Not confirmed."; ok.disabled = false; }}
    }});
    cancel.addEventListener("click", () => {{
      clearInterval(timer);
      box.remove();
      resolve({{detail: "Cancelled: nothing was run."}});
    }});
    const daily = document.createElement("input");
    daily.type = "checkbox";
    daily.id = "hitlDaily";
    const dailyLabel = document.createElement("label");
    dailyLabel.append(daily, " Also authorize this action on this drive for the rest of today");
    dailyLabel.hidden = !DAILY_OK;
    box.append(summary, lead, typed, secret, dailyLabel, msg, ok, cancel);
    (modal.querySelector(".modal-body") || modal).appendChild(box);
  }});
}}

document.getElementById("driveAdminModalConfirm").addEventListener("click", async () => {{
  const params = {{}};
  const devicePath = document.getElementById("paramDevicePath");
  if (devicePath) params.device_path = devicePath.value;
  if (pendingActionId === "build_self_installer") {{
    for (const f of SELF_INSTALLER_OVERRIDE_FIELDS) {{
      const el = document.getElementById(f.id);
      if (el && el.value.trim() !== "") params[f.param] = el.value.trim();
    }}
  }}
  if (pendingActionId === "update_selected") {{
    params.selected = selectedVolumeLabels();
  }}
  if (pendingActionId === "mount_volume" || pendingActionId === "unmount_volume") {{
    const lvName = document.getElementById("paramLvName");
    const mountpoint = document.getElementById("paramMountpoint");
    if (lvName && lvName.value.trim() !== "") params.lv_name = lvName.value.trim();
    if (mountpoint && mountpoint.value.trim() !== "") params.mountpoint = mountpoint.value.trim();
  }}
  if (pendingActionId === "unmount_partition") {{
    params.partition_mountpoint = document.getElementById("paramPartitionMountpoint").value.trim();
  }}
  const consoleEl = document.getElementById("driveAdminModalConsole");
  consoleEl.textContent = "";
  consoleEl.hidden = false;
  document.getElementById("driveAdminModalConfirm").disabled = true;
  const startRes = await fetch("/drive-admin/action", {{
    method: "POST", headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{action_id: pendingActionId, params}}),
  }});
  let startBody = await startRes.json();
  if (startBody.outcome === "confirmation_required") {{
    startBody = await askForConfirmation(startBody.challenge);
  }}
  if (!startBody.job_id) {{
    document.getElementById("driveAdminModalConfirm").disabled = false;
    document.getElementById("driveAdminModal").classList.remove("open");
    const text = startBody.detail || startBody.error || startBody.reason || "done";
    window.location = "/drive-admin?notice=" + encodeURIComponent(text) + "&ok=0";
    return;
  }}
  const job = await pollJobLog(startBody.job_id, consoleEl);
  document.getElementById("driveAdminModalConfirm").disabled = false;
  document.getElementById("driveAdminModal").classList.remove("open");
  const ok = job.outcome === "applied" ? "1" : "0";
  const text = job.detail || "done";
  const deviceQs = devicePath ? "&device=" + encodeURIComponent(devicePath.value) : "";
  window.location = "/drive-admin?notice=" + encodeURIComponent(text) + "&ok=" + ok + deviceQs;
}});
</script>
</body></html>""".encode()


class DriveInventoryError(RuntimeError):
    """Drive enumeration was unavailable; it is not an empty drive list."""


def real_drive_state(runner, *, pds_runner=None) -> list:
    """Every real, non-boot candidate drive - reuses
    `drive_admin.list_candidate_drives` directly, never a second,
    separate enumeration. The pre-authorized drive(s) come back
    pre-marked `is_default`; every other real drive is listed and
    selectable too - "not locked to just that drive" (direct
    instruction)."""
    if runner is None:
        raise DriveInventoryError("drive inventory runner unavailable")
    try:
        return da.list_candidate_drives(runner, pds_runner=pds_runner)
    except Exception as exc:
        if isinstance(exc, DriveInventoryError):
            raise
        raise DriveInventoryError(f"drive inventory failed: {exc}") from exc


def real_volume_state(runner) -> list:
    """Every planned volume (direct feedback: the old version only
    ever showed whatever happened to already be mounted, silently
    hiding INSTALLER_CACHE/SESSION_TEMP/SUBSTRATE/persona
    volumes that simply hadn't been created yet - "makes no sense").
    Includes each volume's real LVM identity (name, real allocated
    size) alongside its live usage when mounted."""
    if runner is None:
        raise VolumeInventoryError("volume inventory runner unavailable")
    try:
        details = drive_installer.collect_volume_details(runner)
    except Exception as exc:
        raise VolumeInventoryError(f"volume inventory failed: {exc}") from exc
    return [{
        "label": d.label, "mountpoint": d.mountpoint, "lv_name": d.lv_name,
        "lv_exists": d.lv_exists, "lv_size_bytes": d.lv_size_bytes,
        "total_bytes": d.total_bytes, "used_bytes": d.used_bytes, "percent_used": d.percent_used,
    } for d in details]


class VolumeInventoryError(RuntimeError):
    """The volume state could not be observed; it is not an empty plan."""


def _collect_system_info(runner) -> tuple[dict, list]:
    """Collect host facts without substituting generic Linux defaults."""
    info, errors = {}, []

    def failed(source, detail):
        errors.append({"source": source, "error": detail})

    try:
        proc = runner.run(["uname", "-r"], timeout=5)
        if proc.returncode == 0 and proc.stdout.strip():
            info["kernel"] = proc.stdout.strip()
        else:
            failed("kernel", proc.stderr.strip() or f"uname exited {proc.returncode}")
    except Exception as exc:
        failed("kernel", f"probe raised {type(exc).__name__}")
    try:
        release = runner.read_text("/etc/os-release")
        pretty = next((line.split("=", 1)[1].strip().strip('"') for line in release.splitlines()
                       if line.startswith("PRETTY_NAME=")), None)
        if pretty:
            info["distro"] = pretty
        else:
            failed("distribution", "PRETTY_NAME is missing from /etc/os-release")
    except Exception as exc:
        failed("distribution", f"/etc/os-release read raised {type(exc).__name__}")
    try:
        cpuinfo = runner.read_text("/proc/cpuinfo")
        model = next((line.split(":", 1)[1].strip() for line in cpuinfo.splitlines()
                      if line.startswith("model name") and ":" in line), None)
        cores = sum(1 for line in cpuinfo.splitlines() if line.startswith("processor"))
        if model:
            info["cpu_model"] = model
        if cores:
            info["cpu_cores"] = str(cores)
        if not model or not cores:
            failed("processor", "model or logical-processor count is missing from /proc/cpuinfo")
    except Exception as exc:
        failed("processor", f"/proc/cpuinfo read raised {type(exc).__name__}")
    try:
        meminfo = runner.read_text("/proc/meminfo")
        found = set()
        for line in meminfo.splitlines():
            key, separator, value = line.partition(":")
            if separator and key in ("MemTotal", "MemAvailable"):
                fields = value.split()
                if fields and fields[0].isdigit():
                    kb = int(fields[0])
                    info["mem_total" if key == "MemTotal" else "mem_available"] = f"{kb // 1048576} GiB ({kb // 1024} MiB)"
                    found.add(key)
        if found != {"MemTotal", "MemAvailable"}:
            failed("memory", "MemTotal or MemAvailable is missing from /proc/meminfo")
    except Exception as exc:
        failed("memory", f"/proc/meminfo read raised {type(exc).__name__}")
    try:
        proc = runner.run(["ip", "-o", "route", "show", "default"], timeout=5)
        if proc.returncode != 0:
            failed("default route", proc.stderr.strip() or f"ip route exited {proc.returncode}")
        else:
            route = next((line for line in proc.stdout.splitlines() if "default" in line.split()), None)
            fields = route.split() if route else []
            if "dev" in fields and fields.index("dev") + 1 < len(fields):
                info["default_iface"] = fields[fields.index("dev") + 1]
            else:
                failed("default route", "no default route interface was observed")
    except Exception as exc:
        failed("default route", f"probe raised {type(exc).__name__}")
    return info, errors


def real_hardware_state(runner) -> dict:
    """Real dependency-check results plus real sensor/NVMe/SMART
    facts and system info from /proc."""
    from repair import RealRunner
    runner = runner or RealRunner()
    import dependencies as dep
    import diagnostics
    import hardware_inventory as hwinv
    errors = []

    def collect(source, function, *args, fallback=None, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            errors.append({"source": source, "error": f"probe failed ({type(exc).__name__})"})
            return fallback

    try:
        dep_results = [{"id": r.id, "ok": r.ok, "detail": r.detail} for r in dep.run_checks(phase=dep.ADHOC)]
    except Exception as exc:
        dep_results = []
        errors.append({"source": "dependencies", "error": f"probe failed ({type(exc).__name__})"})
    sensors = collect("sensors", diagnostics.collect_sensors, runner)
    nvme = collect("nvme", diagnostics.collect_nvme, runner)
    smart = collect("smart", diagnostics.collect_smart, runner)
    sysinfo, system_errors = _collect_system_info(runner)
    errors.extend(system_errors)
    inventory = collect("hardware inventory", hwinv.collect_all, runner)
    return {"dependency_results": dep_results, "sensors": sensors, "nvme": nvme,
            "smart": smart, "sysinfo": sysinfo, "inventory": inventory, "errors": errors}


def render_app_isolation_page(persona: str, plans: list, *,
                              leaks: list, conflicts: list, formats: list,
                              runner=None) -> bytes:
    """Per-application AppData isolation (appdata.py), shown rather than
    asserted only in tests: every app's own data tree, registry, owner
    and overlays, plus what each package format does and does not
    provide on its own.

    This page is read-only: it verifies the selected volume's live mount
    identity, but never mounts or changes files. Applying overlays requires
    a separate runtime implementation and remains outside this page."""
    import appdata

    with_data = [p for p in plans if p.app.has_persistent_data or p.overlays or p.binds]
    total_overlays = sum(len(p.overlays) + len(p.binds) for p in plans)
    guarantees_hold = not leaks and not conflicts and all(p.isolated for p in plans)

    verdict = (
        '<div class="ic-banner ok"><strong>Plan checks passed.</strong> '
        'No application\'s writable layer falls inside another\'s tree, no two '
        'applications claim the same overlay target, and every plan keeps its '
        'data, registry and owner inside its own AppData home.</div>'
        if guarantees_hold else
        f'<div class="ic-banner warn"><strong>Plan checks failed.</strong> '
        f'{len(leaks)} cross-app leak(s), {len(conflicts)} target conflict(s). '
        f'This must be empty before any plan is applied.</div>'
    )

    if runner is None:
        mount_status = ('<div class="ic-banner warn" role="status"><strong>Volume identity not checked.</strong> '
                        'No runtime command runner was supplied.</div>')
    else:
        try:
            mount_root = appdata.verify_appdata_mount(runner, persona)
            mount_status = (f'<div class="ic-banner ok" role="status"><strong>'
                            f'{html.escape(appdata.appdata_label(persona))} mount verified.</strong> '
                            f'{html.escape(mount_root)} is backed by '
                            f'{html.escape(appdata.appdata_label(persona))}.</div>')
        except appdata.AppDataRuntimeError as exc:
            mount_status = (f'<div class="ic-banner warn" role="alert"><strong>AppData volume check failed.</strong> '
                            f'{html.escape(str(exc))}</div>')

    stats = (
        f'<div class="ic-stats">'
        f'<div class="ic-stat"><span class="n">{len(plans)}</span><span class="l">applications</span></div>'
        f'<div class="ic-stat"><span class="n ok">{len(with_data)}</span><span class="l">with personal data</span></div>'
        f'<div class="ic-stat"><span class="n">{total_overlays}</span><span class="l">overlays + binds</span></div>'
        f'<div class="ic-stat"><span class="n {"ok" if not leaks else "warn"}">{len(leaks)}</span><span class="l">cross-app leaks</span></div>'
        f'<div class="ic-stat"><span class="n {"ok" if not conflicts else "warn"}">{len(conflicts)}</span><span class="l">target conflicts</span></div>'
        f'</div>'
    )

    app_rows = []
    app_records = []
    for plan in sorted(plans, key=lambda p: (not (p.overlays or p.binds), p.app.app_id)):
        if plan.binds:
            overlay_html = "<br>".join(
                f'<span class="ov-upper">{html.escape(str(b.host))}</span>'
                f'<span class="ov-arrow"> &rArr; </span>'
                f'<span class="ov-target">{html.escape(str(b.container))}</span>'
                f'{" <span class=ov-none>(read-only)</span>" if b.read_only else ""}'
                for b in plan.binds
            ) + (f'<br><span class="ov-none">bind mounts into the container &middot; '
                 f'image {html.escape(plan.app.image_ref or "NOT PINNED")}</span>')
        elif plan.overlays:
            overlay_html = "<br>".join(
                f'<span class="ov-target">{html.escape(str(o.target))}</span>'
                f'<span class="ov-arrow"> &rarr; </span>'
                f'<span class="ov-upper">{html.escape(str(o.upperdir))}</span>'
                for o in plan.overlays
            )
        else:
            overlay_html = ('<span class="ov-none">no declared data targets &mdash; '
                            'no overlay (stated, not assumed). Unlisted data paths are not audited.</span>')
        app_rows.append(
            "<tr>"
            f"<td>{html.escape(str(plan.app.app_id))}</td>"
            f"<td>{html.escape(str(plan.app.kind))}</td>"
            f"<td>{overlay_html}</td>"
            f"<td>{html.escape(str(plan.registry_db))}</td>"
            f"<td>{html.escape(str(plan.owner_user))}<br><span class='ov-none'>mode {html.escape(str(plan.mode))}</span></td>"
            "</tr>"
        )
        app_records.append({'id':plan.app.app_id,'kind':plan.app.kind,'row':app_rows[-1]})

    app_data = json.dumps(app_records).replace('<', '\\u003c')

    fmt_rows = "".join(
        "<tr>"
        f"<td>{f.name}</td>"
        f'<td>{"<span class=\'drv-ok\'>yes</span>" if f.brings_own_sandbox else "<span class=\'drv-none\'>no</span>"}</td>'
        f"<td>{f.isolation_mechanism}</td>"
        f"<td>{f.data_root_template or '&mdash;'}</td>"
        f"<td>{', '.join(f.baseline_must_supply)}</td>"
        "</tr>"
        for f in formats
    )

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>App Isolation</title><style>{_DRIVE_ADMIN_CSS}
.hw-table {{ width: 100%; border-collapse: collapse; margin: 0 0 1rem; font-size: .8rem;
  background: #14151d; border: 1px solid #262838; border-radius: 8px; overflow: hidden; }}
.hw-table th {{ text-align: left; padding: .5rem .7rem; color: #7d84a0; font-weight: 600;
  font-size: .7rem; text-transform: uppercase; letter-spacing: .05em;
  background: #171923; border-bottom: 1px solid #262838; }}
.hw-table td {{ padding: .5rem .7rem; border-bottom: 1px solid #1c1e29; color: #ccd0e0;
  vertical-align: top; font-family: ui-monospace, monospace; }}
.hw-table tr:last-child td {{ border-bottom: none; }}
.hw-table tr:hover td {{ background: #171b26; }}
.drv-ok {{ color: #6fc28a; font-weight: 600; }}
.drv-none {{ color: #c8a24a; font-weight: 600; }}
.ov-target {{ color: #e7e9f0; }} .ov-arrow {{ color: #5c6180; }}
.ov-upper {{ color: #9db4ec; }} .ov-none {{ color: #7d84a0; font-style: italic; }}
.ic-banner {{ padding: .8rem 1rem; border-radius: 10px; margin: 0 0 1.25rem; font-size: .88rem; line-height: 1.55; }}
.ic-banner.ok {{ background: #14241a; border: 1px solid #2c5238; color: #b7e4c7; }}
.ic-banner.warn {{ background: #2a1f14; border: 1px solid #6b4a1f; color: #f0d5a8; }}
.ic-stats {{ display: flex; gap: 12px; margin: 0 0 1.5rem; flex-wrap: wrap; }}
.ic-stat {{ background: #14151d; border: 1px solid #262838; border-radius: 10px; padding: 12px 18px; min-width: 110px; }}
.ic-stat .n {{ display: block; font-size: 1.5rem; font-weight: 700; color: #e7e9f0; }}
.ic-stat .n.ok {{ color: #6fc28a; }} .ic-stat .n.warn {{ color: #c8a24a; }}
.ic-stat .l {{ display: block; font-size: .72rem; text-transform: uppercase; letter-spacing: .06em; color: #7d84a0; margin-top: 2px; }}
.ic-actions {{ display: flex; gap: 10px; margin: 0 0 1.5rem; }}
.ic-btn {{ padding: .5rem 1rem; background: #23263a; color: #f2f3f8; border-radius: 6px;
  text-decoration: none; font-size: .85rem; font-weight: 600; }}
.ic-btn.active {{ background: #3f63b8; }}
.hw-note {{ color: #8890a6; font-size: .82rem; margin: -.4rem 0 1rem; line-height: 1.55; }}
</style></head>
<body>
<h1>App Isolation</h1>
<p class="subtitle">Every installable application's own data, registry, access and
overlays on {appdata.appdata_root(persona)}</p>

<div class="ic-actions">
  <a class="ic-btn {"active" if persona == "admin" else ""}" href="/app-isolation?persona=admin">admin</a>
  <a class="ic-btn {"active" if persona == "personal" else ""}" href="/app-isolation?persona=personal">personal</a>
</div>

{verdict}
{mount_status}
<p class="hw-note"><strong>Runtime isolation has not been applied or verified.</strong> These checks compare declared paths only; overlays do not by themselves confine a running application.</p>
{stats}

<h2 class="section-title">Applications <span class="ic-count">{len(plans)}</span></h2>
<div role="tablist" aria-label="Application isolation views">
<button role="tab" aria-selected="true" data-isolation-tab="applications">Applications</button>
<button role="tab" aria-selected="false" data-isolation-tab="storage">Storage and overlays</button>
<button role="tab" aria-selected="false" data-isolation-tab="permissions">Identity and permissions</button>
<button role="tab" aria-selected="false" data-isolation-tab="formats">Package formats</button></div>
<section id="isolation-browser"><label for="isolation-search">Find application</label><input id="isolation-search" type="search" placeholder="Name or package type">
<p id="isolation-count" role="status"></p><div id="application-tree" aria-label="Applications grouped by package type"></div>
<button type="button" id="isolation-previous">Previous</button><button type="button" id="isolation-next">Next</button>
<p class="hw-note">Overlay specs are plans; this page verifies the selected AppData volume but does not apply overlays or confine running applications.</p>
<h3 id="isolation-selected">Select an application</h3><p id="isolation-installer"></p>
<table class="hw-table" id="isolation-details"><thead><tr><th>Application</th><th>Kind</th>
<th>Overlay (target &rarr; personal writable layer)</th><th>Own registry</th>
<th>Owner / mode</th></tr></thead><tbody></tbody></table></section>

<section id="isolation-formats" hidden>
<h2 class="section-title">Package formats</h2>
<p class="hw-note">Baseline never duplicates a sandbox a format already provides &mdash;
two permission models that can disagree is worse than one. Where a format brings its
own confinement, only AppData placement is added; where it brings none, Baseline
supplies the whole gap.</p>
<table class="hw-table"><thead><tr><th>Format</th><th>Own sandbox</th>
<th>Isolation mechanism</th><th>Per-app data convention</th>
<th>Baseline must supply</th></tr></thead><tbody>{fmt_rows}</tbody></table></section>
<script id="isolation-data" type="application/json">{app_data}</script>
<script>
const applications=JSON.parse(document.getElementById('isolation-data').textContent),pageSize=50;
let appPage=0,activeIsolationTab='applications',selectedApplication=null;
function selectApplication(app){{selectedApplication=app;document.getElementById('isolation-selected').textContent=app.id;
 const body=document.querySelector('#isolation-details tbody');body.innerHTML=app.row;
 const installer=document.getElementById('isolation-installer');installer.replaceChildren();
 const link=document.createElement('a');link.href='/installer-cache?entry='+encodeURIComponent(app.id);link.textContent='Installer files and updates';installer.append(link);
 for(const row of document.querySelectorAll('#isolation-details tr'))Array.from(row.children).forEach((cell,index)=>{{cell.hidden=activeIsolationTab==='storage'&&index>2||activeIsolationTab==='permissions'&&index===2;}});
}}
function showApplications(){{
 const query=document.getElementById('isolation-search').value.toLowerCase();
 const filtered=applications.filter(app=>(app.id+' '+app.kind).toLowerCase().includes(query));
 appPage=Math.min(appPage,Math.max(0,Math.ceil(filtered.length/pageSize)-1));
 const tree=document.getElementById('application-tree');tree.replaceChildren();const groups=new Map();
 for(const app of filtered.slice(appPage*pageSize,(appPage+1)*pageSize)){{
  if(!groups.has(app.kind)){{const group=document.createElement('details'),summary=document.createElement('summary');summary.textContent=app.kind;group.open=true;group.append(summary);tree.append(group);groups.set(app.kind,group);}}
  const button=document.createElement('button');button.type='button';button.textContent=app.id;button.onclick=()=>selectApplication(app);groups.get(app.kind).append(button);
 }}
 document.getElementById('isolation-count').textContent=filtered.length+' matching applications; page '+(appPage+1)+' of '+Math.max(1,Math.ceil(filtered.length/pageSize));
 document.getElementById('isolation-previous').disabled=appPage===0;document.getElementById('isolation-next').disabled=(appPage+1)*pageSize>=filtered.length;
}}
document.getElementById('isolation-search').oninput=()=>{{appPage=0;showApplications();}};
document.getElementById('isolation-previous').onclick=()=>{{appPage--;showApplications();}};
document.getElementById('isolation-next').onclick=()=>{{appPage++;showApplications();}};
for(const button of document.querySelectorAll('[data-isolation-tab]'))button.onclick=()=>{{
 activeIsolationTab=button.dataset.isolationTab;for(const tab of document.querySelectorAll('[data-isolation-tab]'))tab.setAttribute('aria-selected',String(tab===button));
 document.getElementById('isolation-browser').hidden=activeIsolationTab==='formats';document.getElementById('isolation-formats').hidden=activeIsolationTab!=='formats';
 if(selectedApplication)selectApplication(selectedApplication);
}};
showApplications();
</script>
</body></html>""".encode()


def render_installer_cache_page(report, *, elevated: bool = False) -> bytes:
    """INSTALLER_CACHE transparency report (direct instruction,
    2026-09-30): every artifact this application involves, its original
    installer, the helper that installs it, the settings section that
    configures it, and whether it is actually on the volume right now.

    `report` is an `installer_cache.CacheReport`. Missing artifacts are
    rendered as missing rather than omitted, and files on the volume that
    no catalog entry claims are listed too - both directions of the gap
    matter to anyone trusting a self-replicating build."""
    import installer_cache as ic

    if not report.scanned_ok:
        return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Installer Cache inventory error</title><style>{_DRIVE_ADMIN_CSS}
.ic-banner.warn {{ padding:.8rem 1rem;border:1px solid #6b4a1f;background:#2a1f14;color:#f0d5a8;border-radius:10px; }}
</style></head><body><h1>Installer Cache</h1>
<div class="ic-banner warn" role="alert"><strong>Cache inventory failed.</strong>
The cache contents were not verified, so no artifacts are marked present or missing.</div>
<p>{html.escape(report.scan_detail or 'The cache listing was incomplete.')}</p>
<a href="/installer-cache?root=1">Retry with system permission</a>
</body></html>""".encode()

    if report.mounted:
        banner = (f'<div class="ic-banner ok"><strong>Volume mounted.</strong> '
                  f'{report.root} - {report.mount_detail}</div>')
    else:
        banner = (f'<div class="ic-banner warn"><strong>Not a mount point.</strong> '
                  f'{report.mount_detail}</div>')

    total = len(report.rows)
    stats = (
        f'<div class="ic-stats">'
        f'<div class="ic-stat"><span class="n ok">{report.present_count}</span><span class="l">on the volume</span></div>'
        f'<div class="ic-stat"><span class="n warn">{report.missing_count}</span><span class="l">missing</span></div>'
        f'<div class="ic-stat"><span class="n">{total}</span><span class="l">required for a build</span></div>'
        f'<div class="ic-stat"><span class="n">{len(report.extras)}</span><span class="l">uncatalogued</span></div>'
        f'</div>'
    )

    sections = []
    def _origin_cell(entry) -> str:
        if not entry.registry_ref:
            return entry.origin
        state_cls = "drv-ok" if entry.signature_verified else "drv-none"
        return (f"{entry.origin}<br><code>{entry.pinned_ref or entry.registry_ref + ' (NOT PINNED)'}</code>"
                f"<br><span class='{state_cls}'>{entry.provenance}</span>"
                f"<br><span class='prov-meta'>v{entry.version} &middot; pinned {entry.observed_at}"
                f" &middot; registry publishes {', '.join(entry.attachments)}</span>")

    for kind in (ic.KIND_ISO, ic.KIND_IMAGE, ic.KIND_PACKAGE, ic.KIND_FIRMWARE, ic.KIND_SCRIPT):
        rows = [r for r in report.rows if r.entry.kind == kind]
        if not rows:
            continue
        present = sum(1 for r in rows if r.present)
        body = "".join(
            f'<tr id="cache-entry-{quote(r.entry.entry_id, safe="")}">'
            f'<td>{"<span class=\'drv-ok\'>on volume</span>" if r.present else "<span class=\'drv-none\'>missing</span>"}</td>'
            f"<td>{r.entry.name}</td>"
            f"<td>{_origin_cell(r.entry)}</td>"
            f"<td>{r.entry.install_helper}</td>"
            f"<td>{r.entry.config_section}</td>"
            f"<td>{ic.human_size(r.size_bytes)}</td>"
            "</tr>"
            for r in rows
        )
        sections.append(
            f'<h2 class="section-title">{kind} '
            f'<span class="ic-count">{present}/{len(rows)} present</span></h2>'
            '<table class="hw-table"><thead><tr><th>State</th><th>Artifact</th>'
            '<th>Original installer / source</th><th>Install helper</th>'
            '<th>Configuration</th><th>Size</th></tr></thead>'
            f"<tbody>{body}</tbody></table>"
        )

    if report.extras:
        extra_rows = "".join(
            f"<tr><td>{e.path}</td><td>{ic.human_size(e.size_bytes)}</td></tr>"
            for e in report.extras
        )
        sections.append(
            f'<h2 class="section-title">On the volume but not in the catalog '
            f'<span class="ic-count">{len(report.extras)}</span></h2>'
            '<p class="hw-note">No install helper or configuration references these. '
            'A self-replicating build would not reproduce them, and nothing here '
            'consumes them.</p>'
            '<table class="hw-table"><thead><tr><th>Path</th><th>Size</th></tr></thead>'
            f"<tbody>{extra_rows}</tbody></table>"
        )

    elevated_note = ('<span class="ic-elevated">re-scanned with root</span>' if elevated else "")

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Installer Cache</title><style>{_DRIVE_ADMIN_CSS}
.hw-table {{ width: 100%; border-collapse: collapse; margin: 0 0 1rem; font-size: .82rem;
  background: #14151d; border: 1px solid #262838; border-radius: 8px; overflow: hidden; }}
.hw-table th {{ text-align: left; padding: .5rem .7rem; color: #7d84a0; font-weight: 600;
  font-size: .7rem; text-transform: uppercase; letter-spacing: .05em;
  background: #171923; border-bottom: 1px solid #262838; }}
.hw-table td {{ padding: .45rem .7rem; border-bottom: 1px solid #1c1e29; color: #ccd0e0;
  vertical-align: top; }}
.hw-table tr:last-child td {{ border-bottom: none; }}
.hw-table tr:hover td {{ background: #171b26; }}
.drv-ok {{ color: #6fc28a; font-weight: 600; }}
.drv-none {{ color: #c8a24a; font-weight: 600; }}
.hw-note {{ color: #8890a6; font-size: .82rem; margin: -.4rem 0 .8rem; line-height: 1.5; }}
.ic-banner {{ padding: .8rem 1rem; border-radius: 10px; margin: 0 0 1.25rem; font-size: .88rem; line-height: 1.55; }}
.ic-banner.ok {{ background: #14241a; border: 1px solid #2c5238; color: #b7e4c7; }}
.ic-banner.warn {{ background: #2a1f14; border: 1px solid #6b4a1f; color: #f0d5a8; }}
.ic-stats {{ display: flex; gap: 12px; margin: 0 0 1.5rem; flex-wrap: wrap; }}
.ic-stat {{ background: #14151d; border: 1px solid #262838; border-radius: 10px;
  padding: 12px 18px; min-width: 120px; }}
.ic-stat .n {{ display: block; font-size: 1.5rem; font-weight: 700; color: #e7e9f0; }}
.ic-stat .n.ok {{ color: #6fc28a; }} .ic-stat .n.warn {{ color: #c8a24a; }}
.ic-stat .l {{ display: block; font-size: .72rem; text-transform: uppercase;
  letter-spacing: .06em; color: #7d84a0; margin-top: 2px; }}
.ic-count {{ color: #5c6180; font-weight: 400; text-transform: none; letter-spacing: 0; }}
.ic-actions {{ display: flex; align-items: center; gap: 12px; margin: 0 0 1.5rem; }}
.ic-btn {{ display: inline-block; padding: .55rem 1.1rem; background: #3f63b8; color: #f2f3f8;
  border: none; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: .88rem;
  text-decoration: none; }}
.ic-btn:hover {{ background: #4a72cf; }}
.ic-btn.plain {{ background: #23263a; }} .ic-btn.plain:hover {{ background: #2c3048; }}
.ic-elevated {{ color: #6fc28a; font-size: .82rem; }}
.hw-table code {{ color: #9db4ec; font-size: .76rem; word-break: break-all; }}
.prov-meta {{ color: #7d84a0; font-size: .76rem; }}
</style></head>
<body>
<h1>Installer Cache</h1>
<p class="subtitle">Everything this application installs, where it originally comes from,
and whether it is on {report.root} right now</p>

<div class="ic-actions">
  <a class="ic-btn" href="/installer-cache?root=1">Refresh with Root</a>
  <a class="ic-btn plain" href="/installer-cache">Refresh</a>
  {elevated_note}
</div>

<section aria-labelledby="source-heading"><h2 id="source-heading">Acquire a pinned installer source</h2>
<label for="source-choice">Source</label><select id="source-choice"><option value="ubuntu_base">Ubuntu 24.04 vanilla cloud image</option></select>
<p>Download or verify the existing publisher-pinned file on the mounted INSTALLER_CACHE volume. Corrupt existing files are refused. This creates no VM and does not install or rebuild a drive. HTTPS and SHA256 checks do not prove a detached signature.</p>
<button type="button" id="source-acquire">Acquire / verify selected source</button>
<a href="/installer-cache/source?source=ubuntu_base">Download the verified source file</a>
<p id="source-status" role="status" aria-live="polite"></p><a href="/workloads">Source job history and recovery</a>
</section>
<script>
const sourceButton=document.getElementById('source-acquire'),sourceStatus=document.getElementById('source-status');
sourceButton.onclick=async()=>{{
 sourceButton.disabled=true;
 try{{
  const response=await fetch('/installer-cache/acquire',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{source:document.getElementById('source-choice').value,request_id:'source-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)}})}});
  const submitted=await response.json();if(!response.ok)throw Error(submitted.message||'Acquisition refused');
  sourceStatus.textContent='Source acquisition job '+submitted.job_id+'. Reconnect through Source job history.';
  for(;;){{
   const response=await fetch('/workloads/job?job_id='+encodeURIComponent(submitted.job_id),{{cache:'no-store'}});
   const job=await response.json();if(!response.ok)throw Error(job.message||'Job unavailable');
   if(['completed','failed','interrupted'].includes(job.state)){{sourceStatus.textContent=job.state+': '+((job.result||{{}}).message||'Inspect the source job; no installation inferred.');break;}}
   await new Promise(resolve=>setTimeout(resolve,1000));
  }}
 }}catch(error){{sourceStatus.textContent=error.message;}}
 finally{{sourceButton.disabled=false;}}
}};
</script>
{banner}
{stats}
{''.join(sections)}
</body></html>""".encode()


def _render_inventory(inventory: dict, *, host_drive_links=True) -> str:
    """Every real device on every bus, grouped - the Hardware tab's
    primary content (direct instruction, 2026-09-30: "All hardware must
    show, its not a cpu memory dashboard"). Driver status is shown per
    device because "no driver bound" is exactly what an installer
    operator needs to see."""
    import hardware_inventory as hwinv
    if not inventory:
        return ('<h2 class="section-title">Devices</h2><div class="hw-card unavailable">'
                '<div class="hw-detail"><span class="label">Status:</span>'
                '<span class="value">Not available</span></div>'
                '<p class="hw-setting">Device enumeration did not run (no runner configured).</p></div>')

    import html
    parts = [f'<div class="hw-card unavailable">{html.escape(item["bus"])}: '
             f'{html.escape(item["error"])}</div>' for item in inventory.get("errors", [])]

    def _rows(header: list, rows: list) -> str:
        head = "".join(f"<th>{h}</th>" for h in header)
        body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
        return f'<table class="hw-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'

    pci = inventory.get("pci") or []
    if pci:
        groups = hwinv.group_pci(pci)
        parts.append(f'<h2 class="section-title">PCI Devices ({len(pci)})</h2>')
        for group_name, devices in groups.items():
            parts.append(f'<h3 class="hw-group">{group_name} <span class="count">{len(devices)}</span></h3>')
            parts.append(_rows(
                ["Address", "Device", "Vendor", "Driver"],
                [[html.escape(d.address), html.escape(d.model), html.escape(d.vendor),
                  f'<span class="{"drv-none" if d.kernel_driver is None else "drv-ok"}">{html.escape(d.driver_status)}</span>']
                 for d in devices],
            ))

    block = inventory.get("block") or []
    if block:
        parts.append(f'<h2 class="section-title">Storage Devices ({len(block)})</h2>')
        parts.append(_rows(
            ["Device", "Size", "Bus", "Model", "Serial", "Configuration"],
            [[html.escape('/dev/'+d.name), html.escape(d.size), html.escape(d.transport or '-'), html.escape(d.model or '-'), html.escape(d.serial or '-'),
              '<a href="/drive-admin?serial='+quote(d.serial,safe='')+'">Drive Administration</a>' if host_drive_links and d.serial else
              '<a href="/vms">Virtual disk configuration</a>' if not host_drive_links else 'No serial available; use Drive Administration for inspection'] for d in block],
        ))

    net = inventory.get("net") or []
    if net:
        parts.append(f'<h2 class="section-title">Network Interfaces ({len(net)})</h2>')
        parts.append(_rows(
            ["Interface", "State", "MAC"],
            [[html.escape(n.name),
              f'<span class="{"drv-ok" if n.state == "UP" else "drv-none"}">{html.escape(n.state)}</span>',
              html.escape(n.mac or "-")] for n in net],
        ))

    usb = inventory.get("usb") or []
    if usb:
        parts.append(f'<h2 class="section-title">USB Devices ({len(usb)})</h2>')
        parts.append(_rows(
            ["Bus:Dev", "ID", "Description"],
            [[html.escape(f"{d.bus}:{d.device}"), html.escape(d.usb_id), html.escape(d.description or "-")] for d in usb],
        ))

    return "".join(parts)


def render_hardware_page(*, dependency_results: list, sensors=None, nvme=None, smart=None,
                         sysinfo=None, inventory=None, configuration_html='', target_html='', category_html=None,
                         errors=None) -> bytes:
    """Configuration categories with secondary observed health results.

    Unavailable collectors retain their actual failure reason. Device and
    package controls are supplied by the selected host/guest's native runner.
    """
    sysinfo = sysinfo or {}
    dep_html = "".join(
        f'<div class="action-card {"danger" if not r["ok"] else ""}">'
        f'<div class="action-id">{r["id"]}</div><div class="action-desc">{r["detail"]}</div></div>'
        for r in dependency_results
    ) or '<p class="empty-note">No dependency checks registered.</p>'

    def _hw_detail(label: str, value) -> str:
        shown = "(not detected)" if value in (None, "") else value
        return f'<div class="hw-detail"><span class="label">{label}:</span> <span class="value">{shown}</span></div>'

    def _unavailable(title: str, collector, tool: str) -> str:
        """One collector's honest 'why not' - the real reason it gave."""
        reason = getattr(collector, "reason", "") if collector is not None else f"{tool} not run (no runner configured)"
        return (f'<h2 class="section-title">{title}</h2><div class="hw-card unavailable">'
                f'<div class="hw-detail"><span class="label">Status:</span>'
                f'<span class="value">Not available</span></div>'
                f'<p class="hw-setting">{reason or f"{tool} reported nothing usable"}</p></div>')

    hw_html_parts = []
    if errors:
        rows = "".join(f'<li><strong>{html.escape(str(item.get("source", "observation")))}:</strong> '
                       f'{html.escape(str(item.get("error", "probe failed")))}</li>'
                       for item in errors if isinstance(item, dict))
        if rows:
            hw_html_parts.append(f'<div class="hw-card unavailable" role="alert"><strong>Hardware observations incomplete</strong><ul>{rows}</ul></div>')

    hw_html_parts.append('<h2 class="section-title">System</h2><div class="hw-card">')
    hw_html_parts.append(_hw_detail("Kernel", sysinfo.get("kernel")))
    hw_html_parts.append(_hw_detail("Distro", sysinfo.get("distro")))
    hw_html_parts.append('</div>')

    hw_html_parts.append('<h2 class="section-title">Processor (CPU)</h2><div class="hw-card">')
    hw_html_parts.append(_hw_detail("Model", sysinfo.get("cpu_model")))
    hw_html_parts.append(_hw_detail("Cores", sysinfo.get("cpu_cores")))
    hw_html_parts.append('<p class="hw-setting">📦 <strong>Setting:</strong> CPU microcode choice is configured on the Configuration tab; installed packages are shown under System and other</p>')
    hw_html_parts.append('</div>')

    hw_html_parts.append('<h2 class="section-title">Memory (RAM)</h2><div class="hw-card">')
    hw_html_parts.append(_hw_detail("Total", sysinfo.get("mem_total")))
    hw_html_parts.append(_hw_detail("Available", sysinfo.get("mem_available")))
    hw_html_parts.append('</div>')

    hw_html_parts.append('<h2 class="section-title">Network Interface</h2><div class="hw-card">')
    hw_html_parts.append(_hw_detail("Default route via", sysinfo.get("default_iface")))
    hw_html_parts.append('<p class="hw-setting">⚙️ <strong>Settings:</strong> ethtool (speed, duplex, autoneg), firewall (LAN-only), SSH access</p>')
    hw_html_parts.append('</div>')

    # NVMe - real field names from diagnostics.collect_nvme
    if nvme is not None and getattr(nvme, "available", False):
        devices = getattr(nvme, "devices", []) or []
        hw_html_parts.append('<h2 class="section-title">NVMe Storage</h2>')
        if not devices:
            hw_html_parts.append('<div class="hw-card"><p class="hw-setting">No NVMe devices present on this machine.</p></div>')
        for dev in devices:
            if not isinstance(dev, dict):
                continue
            health = dev.get("health") or {}
            hw_html_parts.append('<div class="hw-card">')
            hw_html_parts.append(_hw_detail("Device", dev.get("path")))
            hw_html_parts.append(_hw_detail("Model", dev.get("model")))
            hw_html_parts.append(_hw_detail("Firmware", dev.get("firmware")))
            if health.get("temperature") is not None:
                hw_html_parts.append(_hw_detail("Temperature", f'{health["temperature"]} K'))
            if health.get("percent_used") is not None:
                hw_html_parts.append(_hw_detail("Wear", f'{health["percent_used"]}% used'))
            hw_html_parts.append('<p class="hw-setting">🔍 <strong>Settings:</strong> SMART monitoring and test schedules are configured on the Configuration tab</p>')
            hw_html_parts.append('</div>')
    else:
        hw_html_parts.append(_unavailable("NVMe Storage", nvme, "nvme-cli"))

    # SMART - dataclass field is `devices`, entries are device/model/temperature/smart_passed.
    # One compact row per disk: `smartctl --scan-open` works unprivileged but
    # `smartctl -a` does not, so an unprivileged run yields a real device list
    # with empty details. That is stated once, not as a wall of "(not detected)".
    if smart is not None and getattr(smart, "available", False):
        disks = [d for d in (getattr(smart, "devices", []) or []) if isinstance(d, dict)]
        hw_html_parts.append(f'<h2 class="section-title">Storage Health (SMART) ({len(disks)})</h2>')
        if not disks:
            hw_html_parts.append('<div class="hw-card"><p class="hw-setting">No SMART-capable devices found.</p></div>')
        else:
            def _smart_status(d: dict) -> str:
                passed = d.get("smart_passed")
                if passed is True:
                    return '<span class="drv-ok">PASSED</span>'
                if passed is False:
                    return '<span class="smart-failed">FAILED</span>'
                return '<span class="drv-none">not readable</span>'

            rows = "".join(
                "<tr>"
                f'<td>{d.get("device") or "-"}</td>'
                f'<td>{d.get("model") or "-"}</td>'
                f'<td>{_smart_status(d)}</td>'
                f'<td>{str(d["temperature"]) + " °C" if d.get("temperature") is not None else "-"}</td>'
                f'<td>{d.get("power_on_hours") if d.get("power_on_hours") is not None else "-"}</td>'
                "</tr>"
                for d in disks
            )
            hw_html_parts.append(
                '<table class="hw-table"><thead><tr><th>Device</th><th>Model</th>'
                '<th>SMART</th><th>Temp</th><th>Power-on hrs</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>'
            )
            if all(d.get("smart_passed") is None for d in disks):
                hw_html_parts.append(
                    '<p class="hw-note">Devices were discovered, but per-device detail needs '
                    'root: <code>smartctl --scan-open</code> runs unprivileged while '
                    '<code>smartctl -a</code> does not. Run the app with privilege to populate '
                    'model, health and temperature.</p>'
                )
    else:
        hw_html_parts.append(_unavailable("Storage Health (SMART)", smart, "smartmontools"))

    # Sensors - real chip readings, not a generic blurb
    if sensors is not None and getattr(sensors, "available", False):
        hw_html_parts.append('<h2 class="section-title">System Sensors (lm-sensors)</h2>')
        for chip in getattr(sensors, "chips", []) or []:
            if not isinstance(chip, dict):
                continue
            hw_html_parts.append('<div class="hw-card">')
            hw_html_parts.append(f'<div class="hw-detail"><span class="label">Chip:</span><span class="value">{chip.get("chip", "?")}</span></div>')
            for feature in chip.get("features", [])[:12]:
                unit = f' {feature["unit"]}' if feature.get("unit") else ""
                hw_html_parts.append(_hw_detail(feature.get("label", "?"), f'{feature.get("value")}{unit}'))
            hw_html_parts.append('</div>')
    else:
        hw_html_parts.append(_unavailable("System Sensors (lm-sensors)", sensors, "lm-sensors"))


    hw_section = ''.join(hw_html_parts)

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Hardware</title><style>{_DRIVE_ADMIN_CSS}
.hw-card {{ background: #14151d; border: 1px solid #262838; border-radius: 10px; padding: 16px; margin: 12px 0; }}
.hw-detail {{ display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px solid #21232f; }}
.hw-detail:last-child {{ border-bottom: none; }}
.hw-detail .label {{ color: #7d84a0; min-width: 140px; font-weight: 600; }}
.hw-detail .value {{ color: #e7e9f0; flex: 1; font-family: ui-monospace, monospace; }}
.hw-setting {{ color: #9db4ec; font-size: 0.9rem; margin-top: 10px; padding-top: 10px; border-top: 1px solid #262838; }}
.hw-card.unavailable {{ border-style: dashed; border-color: #3a3d54; }}
.hw-card.unavailable .value {{ color: #c8a24a; }}
.hw-card.danger {{ border-color: #b6414a; }}
h3.hw-group {{ font-size: .85rem; color: #9aa0ba; margin: 1.4rem 0 .5rem; font-weight: 600; }}
h3.hw-group .count {{ color: #5c6180; font-weight: 400; }}
.hw-table {{ width: 100%; border-collapse: collapse; margin: 0 0 .5rem; font-size: .84rem;
  background: #14151d; border: 1px solid #262838; border-radius: 8px; overflow: hidden; }}
.hw-table th {{ text-align: left; padding: .5rem .7rem; color: #7d84a0; font-weight: 600;
  font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;
  background: #171923; border-bottom: 1px solid #262838; }}
.hw-table td {{ padding: .45rem .7rem; border-bottom: 1px solid #1c1e29;
  color: #ccd0e0; font-family: ui-monospace, monospace; }}
.hw-table tr:last-child td {{ border-bottom: none; }}
.hw-table tr:hover td {{ background: #171b26; }}
.drv-ok {{ color: #6fc28a; }}
.drv-none {{ color: #c8a24a; }}
.smart-failed {{ color: #e5646e; font-weight: 700; }}
.hw-note {{ color: #8890a6; font-size: .82rem; margin: -.1rem 0 1rem; line-height: 1.5; }}
.hw-note code {{ color: #9db4ec; background: #171923; padding: .05rem .3rem; border-radius: 4px; }}
</style></head>
<body>
<h1>Hardware</h1>
<p class="subtitle">Hardware, driver choices and applied configuration</p>
{target_html}
{category_html if category_html is not None else configuration_html + _render_inventory(inventory or {})}
<details><summary>Observed health and diagnostics</summary>

<h2 class="section-title">Health Checks</h2>
<div class="action-grid">{dep_html}</div>

{hw_section}
</details>
</body></html>""".encode()


# ---------------------------------------------------------------------------
# Real, in-memory action-job registry (direct instruction, 2026-09-29:
# "add a console log of what is running and doing to show at the
# bottom of the modal"). A long-running action (build_self_installer -
# real network/QEMU work, genuinely minutes) used to block the entire
# HTTP request with zero feedback until it finished - the browser just
# sat there, indistinguishable from "broken." Now `/drive-admin/action`
# starts the real action in a background thread and returns
# immediately with a `job_id`; the modal polls `/drive-admin/job-log`
# for the real lines `on_progress` is actually reporting, appending
# them live - never a fake/simulated progress bar. Session-lifetime
# in-memory only (no persistence needed - a job that outlives this
# process was never going to be checked on anyway); not pruned, but
# each job holds only a handful of short strings, and this is a
# single-operator admin tool, not a public multi-tenant service.
# ---------------------------------------------------------------------------

_JOBS_LOCK = threading.Lock()
_JOBS: dict = {}


def _hitl_store(deps: dict):
    """The one confirmation store for this server. A confirmation needs this machine's root password or
    passphrase (`recovery_verify_fn`); with none configured nobody can confirm, so no drive action can run."""
    store = deps.get("hitl")
    if store is None:
        audit = hitl.AuditFile(deps["hitl_audit_path"]) if deps.get("hitl_audit_path") else None
        store = deps["hitl"] = hitl.ConfirmationStore(
            verify_secret=deps.get("recovery_verify_fn") or (lambda secret: False), clock=deps["clock"], audit=audit)
    return store


def _run_action_job(job_id: str, sudo_runner, action_id: str, params: dict, pds_runner=None,
                    authorization=None, hitl_store=None, origin=None) -> None:
    def on_progress(line: str) -> None:
        with _JOBS_LOCK:
            _JOBS[job_id]["lines"].append(line)

    try:
        result = da.perform_action(sudo_runner, action_id, params, on_progress=on_progress, pds_runner=pds_runner,
                                   authorization=authorization, hitl_store=hitl_store, origin=origin)
        with _JOBS_LOCK:
            _JOBS[job_id].update(done=True, outcome="applied" if result.ok else "refused", detail=result.detail)
    except Exception as exc:  # a real, unexpected crash must still reach the operator, not hang the poll forever
        with _JOBS_LOCK:
            _JOBS[job_id].update(done=True, outcome="error", detail=f"{type(exc).__name__}: {exc}")


def _operator_users(deps: dict) -> frozenset:
    """Machine accounts that get the limited operator role (settings access.operator_users)."""
    source = deps.get("operator_users")
    names = source() if callable(source) else (source or ())
    return frozenset(n.strip() for n in (names.split(",") if isinstance(names, str) else names) if n.strip())


def _operator_session_seconds(deps: dict) -> float:
    getter = deps.get("operator_session_hours")
    try:
        hours = float(getter() if callable(getter) else (getter if getter is not None else 8))
    except (TypeError, ValueError):
        hours = 8.0
    return min(max(hours, 0.25), 24.0) * 3600


def _run_operation_job(job_id: str, op_id: str, params: dict, origin, deps: dict) -> None:
    def line(text: str) -> None:
        with _JOBS_LOCK:
            _JOBS[job_id]["lines"].append(text)

    try:
        code = ops.execute(op_id, params, origin, print_fn=line, get_setting=deps.get("operation_get_setting"),
                           run=deps.get("operation_run"))
        with _JOBS_LOCK:
            _JOBS[job_id].update(done=True, outcome="applied" if code == 0 else "refused", detail=f"exit code {code}")
    except Exception as exc:  # noqa: BLE001 - must reach the operator, not hang the poll
        with _JOBS_LOCK:
            _JOBS[job_id].update(done=True, outcome="error", detail=f"{type(exc).__name__}: {exc}")
    finally:
        with _JOBS_LOCK:
            record = dict(_JOBS[job_id])
        if deps.get('audit'):
            deps['audit']({'event':'operation_finished','job_id':job_id,'op':op_id,
                           'source':origin.kind,'ts':deps['clock'](),
                           'outcome':record['outcome'],'detail':record['detail']})


def _start_operation_job(deps: dict, op_id: str, params: dict, origin) -> str:
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _JOBS[job_id] = {"lines": [], "done": False, "outcome": None, "detail": None,
                         "op": op_id, "source": origin.kind, "started": deps['clock']()}
    if deps.get('audit'):
        deps['audit']({'event':'operation_started','job_id':job_id,'op':op_id,
                       'source':origin.kind,'ts':deps['clock']()})
    threading.Thread(target=_run_operation_job, args=(job_id, op_id, params, origin, deps), daemon=True).start()
    return job_id


def operation_history(deps):
    if not deps.get('audit_log_path'):
        raise audit_view.AuditReadError("audit log path is not configured")
    records = audit_view.read_tail(deps['audit_log_path'])
    runs = {}
    for event in reversed(records):
        if event.get('event') not in ('operation_started', 'operation_finished'):
            continue
        job_id = event.get('job_id')
        if not job_id:
            continue
        run = runs.setdefault(job_id, {'job_id':job_id,'op':event.get('op',''),
            'source':event.get('source','unknown'),'started':None,
            'outcome':'completion unknown','detail':''})
        if event['event'] == 'operation_started':
            run['started'] = event.get('ts')
        else:
            run.update(outcome=event.get('outcome','completion unknown'),detail=event.get('detail',''))
    with _JOBS_LOCK:
        for job_id, job in _JOBS.items():
            if 'op' in job:
                runs[job_id] = {'job_id':job_id,'op':job['op'],'source':job['source'],
                    'started':job['started'],'outcome':job['outcome'] if job['done'] else 'running',
                    'detail':job['detail'] or ''}
    return sorted(runs.values(),key=lambda r:r.get('started') or 0,reverse=True)[:100]


DEFAULT_STATE_DIR = Path("/var/lib/baseline")     # audit log, signing key and schedules (root-only, mode 0600)

# The only routes reachable without a session: the login screen itself.
# /console only acts for a request from this machine itself (console_switch.is_local), so it needs no login: the person is at the screen.
_PUBLIC_PATHS = frozenset({"/", "/login", "/logout", "/console", "/console/switch"})


def _console_context(deps: dict):
    """The Console/Chat command context (console_commands.Context), built once per server; tests inject `console_context`."""
    if deps.get("console_context") is None:
        import console_commands
        import hardware
        import harness_registry
        import network
        import tether
        snapshot_path = Path("/var/lib/baseline/hardware_snapshot.json")

        def read():
            try:
                return json.loads(snapshot_path.read_text())
            except (OSError, ValueError):
                return None

        def write(data):
            try:
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                snapshot_path.write_text(json.dumps(data, indent=2))
            except OSError:
                pass
        deps["console_context"] = console_commands.Context(
            hardware=hardware, network=network, tether=tether, harness_registry=harness_registry, sessions={},
            snapshot={"read": read, "write": write}, now=deps.get("clock", __import__("time").time))
    return deps["console_context"]


def _shell_run(deps: dict, line: str, harness_id: str) -> list:
    import console_commands
    if len(line) > 1000:
        return ["line too long (limit 1000 characters)"]
    try:
        return console_commands.run(line, _console_context(deps), harness=harness_id)
    except Exception as exc:                           # a failing probe or harness is reported in the transcript, not a 500
        return [f"[{line.split()[0] if line.split() else 'command'}] failed: {exc}"]


def _vault_roots():
    import vault
    return (("USER_ADMIN", "admin", vault.ADMIN_VAULT), ("USER_PERSONAL", "personal", vault.PERSONAL_VAULT))


def _vault_states(deps: dict) -> list:
    import vault
    out = []
    for label, _scope, root in _vault_roots():
        store = vault.Vault(root)
        try:
            out.append({"label": label, "has_passphrase": store.has_passphrase(), "count": len(store.names()),
                        "unlocked": bool(deps.get("vault_passphrase")) and store.has_passphrase()})
        except (vault.VaultError, OSError):
            out.append({"label": label, "has_passphrase": False, "count": 0, "unlocked": False})
    return out


def _vault_for(deps: dict, root: str):
    """The vault bound to the passphrase held in this server's memory, or the plain vault when none is set."""
    import vault
    store = vault.Vault(root)
    return vault.Unlocked(store, deps["vault_passphrase"]) if store.has_passphrase() and deps.get("vault_passphrase") else store


def _vm_host_for(deps: dict) -> vh.VmHost:
    """The VM library for this request; the store folder is a setting, so it is read each time."""
    if deps.get("vm_host") is not None:
        return deps["vm_host"]
    cfg = deps.get("vm_config_path")
    import shutil
    import proxmox_vm_host
    engine = proxmox_vm_host.ProxmoxVmHost if shutil.which("qm") and shutil.which("pvesh") else vh.VmHost
    return engine(vm_page.load_store(cfg, default=str(vh.DEFAULT_STORE)) if cfg else vh.DEFAULT_STORE,
                  persistence_store=vm_page.load_persistence_store(cfg, default=str(vh.DEFAULT_PERSISTENCE_STORE))
                  if cfg else vh.DEFAULT_PERSISTENCE_STORE)


def _kvm_ok(deps: dict) -> bool:
    import os as _os
    return bool(deps["kvm_ok"]()) if deps.get("kvm_ok") else _os.access("/dev/kvm", _os.R_OK | _os.W_OK)


def _container_host_for(deps):
    import shutil
    import container_page
    import distro_containers
    if deps.get('container_host') is not None:
        return deps['container_host']
    if not all(shutil.which(tool) for tool in ('pct', 'pveam', 'pvesh')):
        return None
    return distro_containers.DistroContainers(container_page.load_data(deps.get('vm_config_path')))


class UnifiedHandler(ws.SecureHandlerMixin, http.server.BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html_response(self, status: int, body: bytes, set_cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(body)

    def _binary_response(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str, set_cookie: str | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
        pass

    def _is_json_request(self) -> bool:
        return "application/json" in self.headers.get("Content-Type", "")

    def _read_body_bytes(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def _read_json_body(self) -> dict:
        from web_request_json import read_json_object
        return read_json_object(self.headers,self.rfile)

    def _read_form_body(self) -> dict:
        raw = self._read_body_bytes().decode()
        parsed = parse_qs(raw, keep_blank_values=True)
        return {k: v[0] for k, v in parsed.items()}

    def _read_request_body(self) -> dict:
        """Server-rendered `<form>` submissions (login, admin elevate,
        recovery exit) post as `application/x-www-form-urlencoded`;
        the Drive Administration modal and any programmatic client
        post real JSON - both are real, live request shapes this
        merged handler must accept, not just one of them."""
        return self._read_json_body() if self._is_json_request() else self._read_form_body()

    def _start_drive_job(self, deps: dict, action_id: str, params: dict, authorization, store) -> None:
        # No password field, no `verify_sudo_password` preflight: `PkexecRunner` authenticates per real privileged call
        # via PolicyKit's native agent (direct instruction, 2026-09-29). The human confirmation above is separate.
        pkexec_runner = da.PkexecRunner(executor=deps.get("pkexec_executor"))   # None in a real deployment -> subprocess.run
        gate = deps.get("web_gate")
        if gate is None:
            return self._json(503, {"outcome": "refused", "detail": "refused: no web gate on this server"})
        try:
            origin = gate.origin_for_session(deps["sessions"], self._cookie_token(), "drive_action",
                                             {"action_id": action_id, "params": params}, deps["clock"]())
        except wg.NotFromWebApp as exc:
            return self._json(403, {"outcome": "refused", "detail": f"refused: {exc}"})
        if action_id == 'update_installed_drive':
            jobs=deps.get('workload_jobs')
            if jobs is None:
                return self._json(503, {'outcome':'refused','detail':'Durable installer jobs unavailable'})
            owner=deps['sessions'].get(self._cookie_token(),deps['clock']()).username
            request=hashlib.sha256(json.dumps({'owner':owner,'params':params},sort_keys=True).encode()).hexdigest()
            def update_installed(report):
                result=da.perform_action(pkexec_runner,action_id,params,on_progress=report,
                    pds_runner=deps.get('pds_runner'),authorization=authorization,hitl_store=store,origin=origin)
                return {'ok':result.ok,'message':result.detail}
            try:
                job=jobs.submit('installer','update_installed_drive',
                    {'name':params['device_path'],'backup_id':params['input_bundle'],
                     'destination':params['recovery_folder']},update_installed,
                    request_id='installed-update:'+request,with_progress=True)
                return self._json(200,{'outcome':'started','job_id':job['id'],'durable':True})
            except workload_jobs.JobError as exc:
                return self._json(409,{'outcome':'refused','detail':str(exc)})
        job_id = uuid.uuid4().hex
        with _JOBS_LOCK:
            _JOBS[job_id] = {"lines": [], "done": False, "outcome": None, "detail": None}
        threading.Thread(target=_run_action_job, args=(job_id, pkexec_runner, action_id, params, deps.get("pds_runner"),
                                                       authorization, store, origin), daemon=True).start()
        return self._json(200, {"outcome": "started", "job_id": job_id})

    def _post_operators(self, deps: dict, path: str, body: dict, now: float) -> None:
        """Add or remove an operator account. Needs an admin session AND this machine's root password or passphrase."""
        accounts, verify = deps.get("operator_accounts"), deps.get("recovery_verify_fn")
        if accounts is None or verify is None:
            return self._json(503, {"outcome": "refused", "detail": "refused: operator accounts are not available on this server"})
        if self._throttled("confirm", now):
            return
        secret = body.get("secret", "")
        if not isinstance(secret, str) or not secret or not verify(secret):
            self._record_attempt("confirm", now, ok=False)
            return self._json(403, {"outcome": "refused", "detail": "refused: the credential was not accepted"})
        self._record_attempt("confirm", now, ok=True)
        audit = deps.get("audit") or (lambda record: None)
        username = body.get("username", "")
        try:
            if path == "/operators/add":
                role = body.get("role", "operator")
                accounts.add(username, body.get("password"), role)
                audit({"event": "operator_added", "username": username, "role": role})
            else:
                if not accounts.remove(username):
                    return self._json(404, {"outcome": "refused", "detail": "refused: no such operator"})
                audit({"event": "operator_removed", "username": username})
        except ValueError as exc:
            return self._json(400, {"outcome": "refused", "detail": f"refused: {exc}"})
        return self._json(200, {"outcome": "applied"})

    def _post_operations(self, deps: dict, path: str, body: dict, now: float) -> None:
        gate, scheduler, session = deps.get("web_gate"), deps.get("scheduler"), self._cookie_token()
        if gate is None or scheduler is None:
            return self._json(503, {"outcome": "refused", "detail": "operations are not available on this server"})
        op_id = body.get("op", "")
        try:
            if path == "/operations/run":
                params = ops.validate(op_id, body.get("params", {}))
                origin = gate.origin_for_session(deps["sessions"], session, op_id, params, now)
                return self._json(200, {"outcome": "started", "job_id": _start_operation_job(deps, op_id, params, origin)})
            if path == "/operations/schedule":
                scheduler.set(deps["sessions"], session, op_id, body.get("params", {}), every_hours=body.get("every_hours"))
                return self._json(200, {"outcome": "applied"})
            if path == "/operations/schedule/remove":
                scheduler.remove(deps["sessions"], session, op_id)
                return self._json(200, {"outcome": "applied"})
        except wg.NotFromWebApp as exc:
            return self._json(403, {"outcome": "refused", "detail": f"refused: {exc}"})
        except (ValueError, TypeError) as exc:
            return self._json(400, {"outcome": "refused", "detail": f"refused: {exc}"})
        return self._json(404, {"outcome": "refused", "detail": "no such operation route"})

    def _cookie_token(self) -> str:
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith("session="):
                return part[len("session="):]
        return ""

    def _refuse_unauthenticated(self, deps, now, path: str) -> bool:
        """Nothing beyond the login screen without a credential. There is
        no unauthenticated access and no setting that grants one; recovery mode
        needs a validated login like everything else. Returns True (after
        answering) when the request has no valid session. Applies to every
        route except `_PUBLIC_PATHS`, unknown routes included, so the set
        of routes is not revealed either."""
        session = deps["sessions"].get(self._cookie_token(), now)
        if session is not None:
            if not ops.role_may_reach(session.role, path):
                self._json(403, {"outcome": "refused", "detail": "refused: this login is not authorized for that"}) \
                    if (path.startswith("/api/") or self._is_json_request()) else \
                    self._reject(403, "This login is not authorized for that.")
                return True
            return False
        if path.startswith("/api/") or self._is_json_request():
            self._json(401, {"outcome": "refused", "error": "not authenticated"})
        else:
            self._redirect("/login")
        return True

    def do_GET(self):  # noqa: N802
        deps = self.server.deps  # type: ignore[attr-defined]
        now = deps["clock"]()
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path

        if path not in _PUBLIC_PATHS and self._refuse_unauthenticated(deps, now, path):
            return

        if path in ("/", "/login"):
            session = deps["sessions"].get(self._cookie_token(), now)
            if session is not None:
                return self._redirect("/home")
            return self._html_response(200, sw.render_login_page())

        if path == "/logout":
            deps["sessions"].revoke(self._cookie_token())
            return self._redirect("/login", set_cookie=ws.clear_session_cookie())

        if path == "/console":
            import console_switch
            if not console_switch.is_local(self.client_address[0]):
                return self._html_response(403, console_switch.refused_page())
            return self._html_response(200, console_switch.page())

        if path == "/settings":
            result = sw.handle_settings_view(deps["sessions"], deps["source"], self._cookie_token(), now,
                                              persona_provider=deps.get("persona_provider"))
            if result.outcome != "applied":
                return self._redirect("/login")
            return self._html_response(200, _with_nav(sw.render_settings_page(result.body["settings"]), path))

        if path == "/setup":
            store = deps.get("store")
            if store is None:
                return self._html_response(503, _with_nav(sw.render_machine_passphrase_page(
                    True, "No store is configured on this deployment."), path))
            notice = qs.get("notice", [""])[0]
            return self._html_response(200, _with_nav(sw.render_machine_passphrase_page(
                bool(store.get_machine_passphrase_hash()), notice), path))

        if path == "/api/export-config":
            result = sw.handle_settings_view(deps["sessions"], deps["source"], self._cookie_token(), now,
                                              persona_provider=deps.get("persona_provider"))
            if result.outcome != "applied":
                return self._json(401, {"outcome": "refused", "error": "not authenticated"})
            config = sw.export_install_config(result.body["settings"])
            return self._json(200, config)

        if path.startswith("/admin"):
            result = sw.handle_admin_view(deps["sessions"], self._cookie_token(), now)
            if result.outcome == "refused" and result.status == 401:
                return self._redirect("/login")
            if result.outcome != "applied":
                return self._html_response(result.status, _with_nav(sw.render_admin_page({}, result.body.get("reason", "")), path))
            notice = qs.get("notice", [""])[0]
            elevated = deps["elevation_store"].is_elevated(deps.get("runner"), now) if deps.get("runner") else False
            return self._html_response(200, _with_nav(sw.render_admin_page(
                result.body["settings"], notice, elevated=elevated,
                dependencies=result.body.get("dependencies"),
                dependency_results=result.body.get("dependency_results")), path))

        if path.startswith("/recovery"):
            if not sw.recovery_unlocked(deps, now):
                return self._html_response(401, _with_nav(sw.render_recovery_locked_page(), path))
            result = sw.handle_recovery_view(deps.get("runner"), personas=deps.get("personas", ()))
            if result.outcome != "applied":
                return self._html_response(result.status, _with_nav(sw.render_recovery_page({}, result.body.get("reason", "")), path))
            return self._html_response(200, _with_nav(sw.render_recovery_page(result.body), path))

        if path in ('/install-plan/draft', '/recipes/draft', '/install-plan/display'):
            store = deps.get('draft_store')
            if store is None:
                return self._json(503, {'ok':False, 'message':'Durable configuration draft storage unavailable'})
            kind = 'installer-display' if path == '/install-plan/display' else 'installer' if path.startswith('/install-plan') else 'recipe'
            session = deps['sessions'].get(self._cookie_token(), now)
            try:
                return self._json(200, {'ok':True, 'draft':store.get(session.username, kind)})
            except (OSError, ValueError, sqlite3.Error) as exc:
                return self._json(503, {'ok':False, 'message':'Draft could not be read: ' + str(exc)})

        if path == '/install-plan/input-bundle':
            import installer_inputs
            jobs=deps.get('workload_jobs')
            if jobs is None or not deps.get('installer_bundle_root'):
                return self._json(503,{'message':'Installer bundle storage unavailable'})
            try:
                job=jobs.get(qs.get('job_id',[''])[0])
                if job['kind']!='installer' or job['action']!='prepare_inputs':
                    raise installer_inputs.InputError('Not an installer input preparation job')
                owner=deps['sessions'].get(self._cookie_token(),now).username
                folder=Path(deps['installer_bundle_root'])/hashlib.sha256(owner.encode()).hexdigest()/job['name']
                return self._json(200,installer_inputs.verify(folder))
            except (installer_inputs.InputError,workload_jobs.JobError,OSError) as exc:
                return self._json(409,{'message':str(exc),'ready':False,'executed':False})

        if path == "/installation-readiness":
            import installation_readiness
            report=installation_readiness.collect(deps["runner"])
            return self._html_response(200, _with_nav(installation_readiness.render(report).encode(), path))

        if path == "/install-plan":
            import install_plan_page
            return self._html_response(200, _with_nav(install_plan_page.render(), path))

        if path == "/ceph":
            import ceph_setup
            job = deps.get("ceph_job")
            state = job.state() if job is not None else {"phase": "idle", "message": ""}
            installed = ceph_setup.is_installed(deps.get("ceph_runner"))
            refresh = "<meta http-equiv='refresh' content='5'>" if state["phase"] == "running" else ""
            body = (f"<!doctype html><html><head><meta charset='utf-8'><title>Ceph</title>{refresh}</head><body><h1>Ceph</h1>"
                    f"<p>Ceph packages: <b>{'installed' if installed else 'not installed'}</b></p>"
                    f"<p>{html.escape(state['message'])}</p>"
                    + ("" if installed else '<form method="post" action="/ceph/install"><button type="submit">Install Ceph packages</button>'
                       "</form><p>Needs the internet (Proxmox's repository). Creating monitors and OSDs is done in Proxmox "
                       "(node &gt; Ceph) once you decide which drives to give it.</p>")
                    + "</body></html>").encode()
            return self._html_response(200, _with_nav(body, path))

        if path == "/security":
            import ai_setup_page
            pending = {u: (v[0], v[1]) for u, v in deps.get("tfa_pending", {}).items()}
            return self._html_response(200, _with_nav(ai_setup_page.render_security(
                pending, qs.get("notice", [""])[0][:200].replace("+", " ")), path))

        if path == "/vault":
            import ai_setup_page
            import vault
            return self._html_response(200, _with_nav(ai_setup_page.render_vault(
                _vault_states(deps), qs.get("notice", [""])[0][:200].replace("+", " ")), path))

        if path in ("/ai-setup", "/ai-setup/claude"):
            import ai_setup_page
            import providers
            import vault
            if path == "/ai-setup/claude":
                session = deps.get("claude_setup")
                state = session.state() if session is not None else {"phase": "idle", "url": None,
                                                                  "message": "no sign-in is in progress"}
                return self._html_response(200, _with_nav(ai_setup_page.render_claude(state), "/ai-setup"))
            status = []
            for label, root in (("USER_ADMIN", vault.ADMIN_VAULT), ("USER_PERSONAL", vault.PERSONAL_VAULT)):
                try:
                    status += [dict(s, name=f"{s['name']} ({label})") for s in vault.Vault(root).status()]
                except (vault.VaultError, OSError):
                    pass
            notice = qs.get("notice", [""])[0][:200]
            return self._html_response(200, _with_nav(ai_setup_page.render_overview(
                providers.check_providers(), status, [notice] if notice else [], providers.harness_status()), "/ai-setup"))

        if path == "/home":
            import home_page
            return self._html_response(200, _with_nav(home_page.render(), path))

        if path == "/environments":
            import environments
            try:
                host = _vm_host_for(deps)
                isos = [i["name"] if isinstance(i, dict) else str(i)
                        for i in vm_page.available_isos(host, deps.get("vm_iso_dir") or vh.DEFAULT_ISO_DIR)]
                vms = host.list_vms()
            except (vh.VmError, OSError, ValueError) as exc:
                return self._html_response(200, _with_nav(environments.render([]).replace(
                    b"<table>", ("<p role='alert'>Inventory unavailable: " + html.escape(str(exc))).encode() + b"</p><table>"), path))
            return self._html_response(200, _with_nav(environments.render(environments.catalogue(
                isos, [{"name": getattr(v, "name", None) or (v.get("name") if isinstance(v, dict) else None)} for v in vms])), path))

        if path == "/shell":
            import chat_page
            import providers
            return self._html_response(200, _with_nav(chat_page.render_shell(
                deps.setdefault("shell_transcript", []), [(h["id"], h["name"]) for h in providers.HARNESSES]), path))

        if path == "/chat":
            import chat_page
            import providers
            return self._html_response(200, _with_nav(chat_page.render(
                deps.setdefault("chat_history", []), [(h["id"], h["name"]) for h in providers.HARNESSES],
                qs.get("notice", [""])[0][:200]), path))

        if path == "/network":
            import network
            import network_view
            import providers
            try:
                facts = network.check_lifeline()
            except (OSError, network.NetworkProbeError) as exc:       # a failed probe is reported, never a blank 500
                facts = [{"fact": "interface_inventory", "ok": False, "detail": f"network probe failed: {exc}"}]
            try:
                interfaces = network.list_interfaces()
            except (OSError, network.NetworkProbeError) as exc:
                interfaces = []
                facts.append({"fact": "interface_inventory", "ok": False, "detail": str(exc)})
            page = network_view.render(network_view.build_rows(facts, interfaces, providers.check_providers(), network))
            notice = html.escape(qs.get("notice", [""])[0][:200].replace("+", " "))
            extra = (f"<p>{notice}</p>" if notice else "") + ('<form method="post" action="/network/tether">'
                                                              '<button type="submit">Connect a USB tether</button></form>')
            return self._html_response(200, _with_nav(page.replace(b"</body>", extra.encode() + b"</body>"), path))

        if path == "/sensors":
            import diagnostics
            import repair
            import sensors_view
            try:
                rows = sensors_view.collect_rows(deps.get("runner") or repair.RealRunner(), diagnostics)
            except (OSError, ValueError, KeyError, AttributeError) as exc:
                rows = [("error", "sensor collection failed", str(exc), "")]
            return self._html_response(200, _with_nav(sensors_view.render(rows), path))

        if path == "/tools":
            import tools_page
            return self._html_response(200, _with_nav(tools_page.render(deps.get("tools_results") or tools_page.gather()), path))

        if path == "/recipes":
            import recipe_page
            return self._html_response(200, _with_nav(recipe_page.render(), path))

        if path == "/app-isolation":
            import appdata
            persona = qs.get("persona", ["personal"])[0]
            if persona not in drive_installer.DEFAULT_PERSONAS:
                persona = "personal"
            plans = appdata.plan_all(persona)
            return self._html_response(200, _with_nav(render_app_isolation_page(
                persona, plans,
                leaks=appdata.cross_app_leaks(plans),
                conflicts=appdata.target_conflicts(plans),
                formats=appdata.supported_formats(), runner=deps["runner"]), path))

        if path == '/installer-cache/source':
            import installer_sources,installer_cache
            if qs.get('source',[''])[0]!='ubuntu_base':return self._json(400,{'message':'Unsupported source'})
            try:
                root=deps.get('installer_cache_root',installer_cache.DEFAULT_CACHE_ROOT)
                lock=installer_sources.locks(deps['runner'],root).get('ubuntu_base')
                if lock is None:raise installer_sources.SourceError('Pinned Ubuntu installer file has not been acquired')
                with Path(lock['path']).open('rb') as stream:
                    self.connection.settimeout(30)
                    self.send_response(200);self.send_header('Content-Type','application/octet-stream')
                    self.send_header('Content-Length',str(os.fstat(stream.fileno()).st_size))
                    self.send_header('Content-Disposition','attachment; filename="'+Path(lock['path']).name+'"')
                    self.end_headers()
                    try:
                        while chunk:=stream.read(1024*1024):self.wfile.write(chunk)
                    except OSError:
                        self.close_connection=True
                        return
                return
            except (installer_sources.SourceError,OSError,KeyError) as exc:
                return self._json(409,{'message':str(exc)})

        if path == "/installer-cache":
            # "Refresh with Root": the unprivileged scan can miss a
            # root-only mount or a directory it cannot read. ?root=1
            # swaps in PkexecRunner, which authenticates per call via
            # PolicyKit's own agent - same mechanism Drive Administration
            # already uses, so there is no password field here either.
            import installer_cache as ic
            elevated = qs.get("root", [""])[0] == "1"
            if elevated:
                scan_runner = da.PkexecRunner(executor=deps.get("pkexec_executor"))
            else:
                scan_runner = deps.get("runner")
            if scan_runner is None:
                report = ic.CacheReport(root=ic.DEFAULT_CACHE_ROOT, mounted=False,
                                        mount_detail="no runner configured - cannot read the volume",
                                        scanned_ok=False,
                                        scan_detail="no inventory runner is configured")
            else:
                try:
                    report = ic.reconcile(scan_runner)
                except ic.CacheScanError as exc:
                    report = ic.CacheReport(root=ic.DEFAULT_CACHE_ROOT,
                                            mounted=bool(exc.mounted),
                                            mount_detail=exc.mount_detail,
                                            scanned_ok=False, scan_detail=str(exc))
            return self._html_response(200, _with_nav(
                render_installer_cache_page(report, elevated=elevated), path))

        if path == "/audit":
            try:
                audit = operations_page.render_audit_page(audit_view.read_tail(deps["audit_log_path"], 200)
                                                          if deps.get("audit_log_path") else [], error=None if deps.get("audit_log_path") else "audit log path is not configured")
                status = 200 if deps.get("audit_log_path") else 503
            except audit_view.AuditReadError as exc:
                audit = operations_page.render_audit_page([], error=str(exc))
                status = 503
            return self._html_response(status, _with_nav(audit, path))

        if path == "/remote-access":
            status = deps["remote_status"]() if deps.get("remote_status") else remote_access.collect(deps["runner"])
            configuration = deps['source'].current_settings() if deps.get('source') else None
            return self._html_response(200, _with_nav(operations_page.render_remote_access_page(status, configuration=configuration), path))

        if path == "/approvals":
            return self._html_response(200, _with_nav(
                operations_page.render_approvals_page(_hitl_store(deps).list_all_daily()), path))

        if path == "/operators":
            accounts = deps.get("operator_accounts")
            return self._html_response(200, _with_nav(
                operations_page.render_operators_page(accounts.roles() if accounts else {}), path))

        if path in ("/workloads", "/workloads/jobs", "/workloads/job"):
            jobs = deps.get("workload_jobs")
            if jobs is None:
                return self._json(503, {"error":"durable workload storage is not configured"})
            if path == "/workloads":
                return self._html_response(200, _with_nav(workload_page.render(jobs.listing()),path))
            if path == "/workloads/jobs":
                return self._json(200,jobs.listing())
            try:
                return self._json(200,jobs.get(qs.get("job_id",[""])[0]))
            except workload_jobs.JobError as exc:
                return self._json(404,{"error":str(exc)})

        if path == '/operations/history':
            try:
                return self._json(200, {'runs':operation_history(deps)})
            except audit_view.AuditReadError as exc:
                return self._json(503, {'error': str(exc)})

        if path == "/operations":
            scheduler = deps.get("scheduler")
            try:
                history = operation_history(deps)
                history_error = None
            except audit_view.AuditReadError as exc:
                history = []
                history_error = str(exc)
            return self._html_response(200, _with_nav(
                operations_page.render_operations_page(ops.OPERATIONS, scheduler.listing() if scheduler else [],
                                                       deps.get("tamper_alerts"), history=history,
                                                       history_error=history_error), path))

        if path.startswith("/drive-admin/actions"):
            return self._json(200, {"actions": da.describe_actions()})

        if path.startswith("/drive-admin/job-log"):
            job_id = qs.get("job_id", [""])[0]
            with _JOBS_LOCK:
                job = _JOBS.get(job_id)
                if job is None:
                    return self._json(404, {"error": "unknown job"})
                return self._json(200, dict(job))

        if path.startswith("/drive-admin/screendump"):
            # Direct instruction, 2026-09-29: "keep things improving" -
            # a real, safe way to see a running install's actual
            # current screen, replacing a manual raw-socket `nc`
            # command that accidentally sent `quit` and killed a real
            # in-progress install. Never sends anything but the one
            # real `screendump` command, and never fakes a blank image
            # when no install is actually running - a genuine error
            # instead.
            import drive_setup_install as dsi
            workspace = Path(qs.get("workspace", ["/var/tmp/baseline-self-installer"])[0])
            monitor_socket = workspace / "monitor.sock"
            if not monitor_socket.exists():
                return self._json(404, {"error": f"no active install found at {monitor_socket}"})
            try:
                png_bytes = dsi.capture_live_screendump_png(monitor_socket)
            except Exception as exc:
                return self._json(502, {"error": f"screendump capture failed: {exc}"})
            return self._binary_response(200, png_bytes, "image/png")

        if path == "/drive-admin/approvals":
            return self._json(200, {"grants": _hitl_store(deps).list_grants(self._cookie_token())})

        if path.startswith("/drive-admin"):
            runner = deps.get("runner")
            drive_error = ""
            try:
                drives = real_drive_state(runner, pds_runner=deps.get("pds_runner"))
            except DriveInventoryError as exc:
                drives = []
                drive_error = str(exc)
            volume_error = ""
            try:
                volumes = real_volume_state(runner)
            except VolumeInventoryError as exc:
                volumes = []
                volume_error = str(exc)
            notice = qs.get("notice", [""])[0]
            notice_ok = qs.get("ok", [None])[0]
            notice_ok = {"1": True, "0": False}.get(notice_ok)  # None when no action just ran at all
            acted_on_path = qs.get("device", [None])[0]  # which drive card an action just targeted, if any
            return self._html_response(200, _with_nav(
                render_drive_admin_page(drives=drives, volumes=volumes, actions=da.describe_actions(),
                                         notice=notice, notice_ok=notice_ok, acted_on_path=acted_on_path,
                                         daily_ok=deps["sessions"].get(self._cookie_token(), now).role.startswith(wg.BOT_PREFIX),
                                         selected_serial=qs.get("serial", [""])[0], volume_error=volume_error,
                                         drive_error=drive_error),
                path))

        if path.startswith('/installer-icons/'):
            import installer_inputs
            name=path.rsplit('/',1)[-1]
            if not re.fullmatch(r'[a-z0-9-]+\.(png|svg)',name):
                return self._json(404,{'error':'Unknown installer icon'})
            try:
                icon=installer_inputs.source_root(__file__)/'packaging/installer-icons'/name
                if icon.is_symlink() or icon.stat().st_size>512*1024:raise OSError('Invalid icon asset')
                data=icon.read_bytes()
            except (installer_inputs.InputError,OSError):
                return self._json(404,{'error':'Native application icon unavailable'})
            self.send_response(200);self.send_header('Content-Type','image/svg+xml' if name.endswith('.svg') else 'image/png')
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','private, max-age=3600')
            self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data);return

        if path == '/install-plan/discovery':
            import install_plan_page,application_bundle,install_plan
            try:
                found=deps.get('install_plan_discovery',install_plan_page.discover_current)()
                entries=install_plan_page.catalog_entries(deps.get('installer_repo_root'),
                    catalog_directory=deps.get('application_catalog_root'))
                return self._json(200,{'drives':found['drives'],'plan':install_plan.autofill(found),
                    'os_choices':sorted(install_plan.SUPPORTED_OS),'applications':list(application_bundle.APPS),
                    'application_entries':entries,
                    'selected_serial':deps.get('installer_selected_serial',''),
                    'protected_serials':deps.get('installer_protected_serials',[])})
            except (install_plan.PlanError,OSError,ValueError,KeyError) as exc:
                return self._json(503,{'message':'Current installer discovery failed: '+str(exc)})

        if path == "/containers/backups":
            import container_page, container_backup
            dest=parse_qs(urlparse(self.path).query).get('destination',[''])[0]
            sets=[];error=''
            if dest:
                try:sets=container_backup.listing(dest,deps.get('container_backup_run'))
                except (vh.VmError,OSError,ValueError,RuntimeError) as exc:error=str(exc)
            return self._html_response(200,_with_nav(container_page.render_backups(dest,sets,error),path))

        if path == "/containers":
            import container_page
            try:
                page = container_page.render(_container_host_for(deps))
            except (vh.VmError, OSError, ValueError) as exc:
                page = container_page.render(unavailable=str(exc))
            return self._html_response(200, _with_nav(page, path))

        if path == "/vms/status":
            try:
                host = _vm_host_for(deps)
                return self._json(200, vm_page.status_snapshot(host.list_vms(), host.list_bases()))
            except (vh.VmError, OSError, ValueError) as exc:
                return self._json(503, {"error": f"VM inventory unavailable: {exc}", "state": "unknown"})

        if path == "/vms":
            iso_dir = deps.get("vm_iso_dir") or vh.DEFAULT_ISO_DIR
            notice_ok = {"1": True, "0": False}.get(qs.get("ok", [""])[0])
            inventory_error = ""
            try:
                host = _vm_host_for(deps)
                vms, bases = host.list_vms(), host.list_bases()
            except (vh.VmError, OSError, ValueError) as exc:
                page = vm_page.render_vms_page(
                    store="Unavailable", free_gb="unknown", kvm_ok=_kvm_ok(deps), isos=[],
                    bases=[], vms=[], backend="Unavailable", persistence_store="Unavailable",
                    notice=qs.get("notice", [""])[0][:300], notice_ok=notice_ok,
                    default_display=vh.default_display(os.environ), inventory_error=str(exc))
                return self._html_response(200, _with_nav(page, path))
            homepage = ""
            homepage_error = ""
            if hasattr(host, "guest_homepage"):
                try:
                    homepage = host.guest_homepage()
                except (vh.VmError, OSError, ValueError) as exc:
                    homepage_error = str(exc)
            return self._html_response(200, _with_nav(vm_page.render_vms_page(
                store=str(host.store), free_gb=round(host.free_bytes(host.store) / 2**30), kvm_ok=_kvm_ok(deps),
                isos=vm_page.available_isos(host, iso_dir), bases=bases, vms=vms,
                backend=getattr(host, "backend", "Local QEMU"), persistence_store=str(host.persistence_store),
                homepage=homepage, homepage_error=homepage_error,
                notice=qs.get("notice", [""])[0][:300], notice_ok=notice_ok,
                default_display=vh.default_display(os.environ), inventory_error=inventory_error), path))

        if path.startswith("/hardware"):
            import hardware_configuration as hc
            import hardware_inventory
            import structured_controls
            runner = deps.get("runner")
            target = qs.get('vm',[''])[0]
            machine_error = ''
            try:
                host = _vm_host_for(deps)
                machines = host.list_vms()
            except (RuntimeError, OSError, ValueError, vh.VmError) as exc:
                host, machines = None, []
                machine_error = '<p role="alert">VM target listing unavailable: '+html.escape(str(exc))+'</p>'
            options = '<option value="">This host</option>' + ''.join(
                f'<option value="{html.escape(vm["name"],quote=True)}" {"selected" if vm["name"]==target else ""}>{html.escape(vm["name"])}</option>' for vm in machines)
            target_html = f'<form method="get" action="/hardware"><label>Configure <select name="vm" onchange="this.form.submit()">{options}</select></label></form>'+machine_error
            configuration_html = ''
            driver_sections = {}
            import hardware_tabs
            packages = {'available':False,'error':'Target configuration unavailable'}
            try:
                if target:
                    if target not in {vm['name'] for vm in machines}:raise RuntimeError('Unknown managed VM')
                    runner = hc.GuestRunner(host,target)
                    state = {'dependency_results':[], 'inventory':{'pci':hardware_inventory.collect_pci(runner)}}
                else:
                    state = real_hardware_state(runner)
                    settings = deps['source'].current_settings() if deps.get('source') else {}
                    configuration_html = sw.render_configuration_sections({key:settings[key] for key in ('drivers','proxmox','_live_interfaces') if key in settings})
                import hardware_inventory
                module_packages = {}
                for category, devices in hardware_inventory.group_pci((state.get('inventory') or {}).get('pci') or []).items():
                    driver_sections[category] = hc.render_driver_controls(runner,devices,target,module_packages)
                packages = hardware_tabs.package_state(runner)
            except (RuntimeError,vh.VmError,OSError) as exc:
                state={'dependency_results':[], 'inventory':{}}
                configuration_html += f'<p role="alert">Configuration unavailable: {html.escape(str(exc))}</p>'
            configuration_html += '<p>Choose a category to configure its devices or inspect associated packages and firmware.</p>' + structured_controls.script()
            category_html = hardware_tabs.render(state.get('inventory') or {},configuration_html=configuration_html,
                driver_sections=driver_sections,packages=packages,target=target,
                render_inventory=lambda inventory:_render_inventory(inventory,host_drive_links=not bool(target)))
            return self._html_response(200, _with_nav(render_hardware_page(**state,target_html=target_html,category_html=category_html), path))

        if path.startswith("/master-config"):
            import master_configuration
            settings = deps['source'].current_settings() if deps.get('source') else {}
            admin_result = sw.handle_admin_view(deps['sessions'], self._cookie_token(), now)
            elevated = deps['elevation_store'].is_elevated(deps.get('runner'), now) if deps.get('runner') else False
            from dataclasses import asdict
            import installer_cache, appdata, container_page
            additional, errors = [], []
            additional.append(('Hardware and Remote access', '/hardware', {'configuration_source': 'Settings / drivers, diagnostics, proxmox, ssh and firewall above; device driver bindings are observed on the Hardware tab.'}))
            additional.append(('Installer Cache / declared sources', '/installer-cache', [asdict(entry) for entry in installer_cache.catalog()]))
            additional.append(('App Isolation / declared policy', '/app-isolation', {
                persona: [asdict(plan) for plan in appdata.plan_all(persona)]
                for persona in drive_installer.DEFAULT_PERSONAS}))
            additional.append(('Distro containers / storage', '/containers', {'data_store': container_page.load_data(deps.get('vm_config_path'))}))
            accounts = deps.get('operator_accounts')
            if accounts:
                additional.append(('Operators / roles', '/operators', accounts.roles()))
            else:
                errors.append('Operator role configuration unavailable')
            draft_store = deps.get('draft_store')
            if draft_store is None:
                errors.append('Durable installer/recipe draft source unavailable')
            else:
                session = deps['sessions'].get(self._cookie_token(), now)
                for kind, title, link in (('installer','Installer plan / saved draft','/install-plan'), ('recipe','Environment recipes / saved draft','/recipes')):
                    try:
                        draft = draft_store.get(session.username, kind)
                        additional.append((title, link, {'status':'Saved draft; not applied. Validate again before execution.', **draft} if draft else {'status':'No saved draft for this user.'}))
                    except (OSError, ValueError, sqlite3.Error) as exc:
                        errors.append(title + ' unavailable: ' + str(exc))
            additional.append(('Recovery, Approvals, Audit and Workload jobs', '/recovery', {'configuration_source': 'Recovery and access settings are in Admin above. Approvals, audit entries and job results are operational records, available in their owning tabs.'}))
            scheduler = deps.get('scheduler')
            if scheduler:
                additional.append(('Operations / schedules', '/operations', scheduler.listing()))
            else:
                errors.append('Operation schedule source unavailable')
            try:
                host = _vm_host_for(deps)
                additional.append(('Virtual machines / storage', '/vms', {
                    'store': str(host.store), 'persistence_store': str(host.persistence_store)}))
                additional.append(('Virtual machines / configuration', '/vms', [
                    {key: value for key, value in vm.items() if key in
                     ('name', 'cpus', 'memory_mb', 'disk_gb', 'firmware', 'base', 'persistence_gb', 'recipe', 'homepage')}
                    for vm in host.list_vms()]))
            except (RuntimeError, OSError, vh.VmError) as exc:
                errors.append('Virtual machine configuration unavailable: ' + str(exc))
            return self._html_response(200, _with_nav(master_configuration.render(
                settings, admin_result.body.get('settings', {}), elevated=elevated,
                additional=additional, errors=errors), path))

        if path == "/api/detect":
            result = cpw.handle_detect(deps["runner"], vg_name=deps.get("vg_name", drive_installer.DEFAULT_VG_NAME))
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        if path == "/api/active-persona":
            result = cpw.handle_active_persona(deps["runner"])
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        result = {"outcome": "handed_off", "reason": f"no route for {path!r}"}
        self._json(404, result)

    def do_POST(self):  # noqa: N802
        deps = self.server.deps  # type: ignore[attr-defined]
        now = deps["clock"]()
        path = self.path.split("?", 1)[0]       # routes never depend on a query string

        # A POST must come from this site (SameSite=Strict on the cookie is the first line of defence).
        if not ws.origin_ok(self.headers, has_cookie=bool(self._cookie_token())):
            return self._reject(403, "cross-site request refused")

        if path not in _PUBLIC_PATHS and self._refuse_unauthenticated(deps, now, path.split("?", 1)[0]):
            return

        try:
            body = self._read_request_body()
        except ValueError as exc:
            return self._json(400,{"ok":False,"message":str(exc)})

        if path == '/hardware/driver':
            import hardware_configuration as hc
            try:
                if set(body) != {'address','pci_id','module','vm'} or not all(isinstance(v,str) for v in body.values()):
                    raise RuntimeError('Invalid driver request')
                gate=deps.get('web_gate')
                if gate is None:raise RuntimeError('Web action authorization unavailable')
                gate.origin_for_session(deps['sessions'],self._cookie_token(),'hardware_driver',body,now)
                runner = hc.GuestRunner(_vm_host_for(deps),body['vm']) if body['vm'] else da.PkexecRunner(executor=deps.get('pkexec_executor'))
                result=hc.load_driver(runner,address=body['address'],pci_id=body['pci_id'],module=body['module'])
                if deps.get('audit'):deps['audit']({'event':'hardware_driver_result','target':body['vm'] or 'host',**result})
                return self._json(200,result)
            except (RuntimeError,vh.VmError,OSError,ValueError) as exc:
                return self._json(409,{'outcome':'refused','detail':str(exc)})

        if path == "/network/tether":
            import chat_page
            import tether
            severity, message = chat_page.tether_message(tether.auto_tether())
            if deps.get("audit"):
                deps["audit"]({"event": "tether_requested", "severity": severity})
            return self._redirect("/network?notice=" + html.escape(message).replace(" ", "+")[:200])

        if path == "/shell/run":
            line = str(body.get("line", "")).strip()
            transcript = deps.setdefault("shell_transcript", [])
            if line:
                transcript.append(f"baseline> {line[:80]}")
                transcript.extend(_shell_run(deps, line, str(body.get("harness", "claude"))))
                del transcript[:-200]
            return self._redirect("/shell")

        if path == "/chat/ask":
            import chat_page
            try:
                question = chat_page.clean_question(str(body.get("question", "")))
            except ValueError as exc:
                return self._redirect("/chat?notice=" + html.escape(str(exc)).replace(" ", "+"))
            answer = " ".join(_shell_run(deps, "ask " + question, str(body.get("harness", "claude"))))
            deps.setdefault("chat_history", []).append((question, answer))
            del deps["chat_history"][:-20]
            return self._redirect("/chat")

        if path == "/ceph/install":
            import ceph_setup
            job = deps.get("ceph_job")
            if job is None or job.state()["phase"] != "running":
                deps["ceph_job"] = ceph_setup.InstallJob(deps.get("ceph_runner"))
                deps["ceph_job"].start()
                if deps.get("audit"):
                    deps["audit"]({"event": "ceph_install_requested"})
            return self._redirect("/ceph")

        if path in ("/security/tfa/start", "/security/tfa/confirm"):
            import tfa_setup
            notice = ""
            try:
                userid = tfa_setup.check_userid(str(body.get("userid", "")))
                pending = deps.setdefault("tfa_pending", {})
                if path == "/security/tfa/start":
                    secret = tfa_setup.new_secret()
                    pending[userid] = (secret, tfa_setup.otpauth_uri(userid, secret, issuer="Baseline " + os.uname().nodename))
                    notice = f"Key made for {userid}; confirm it with a code from your authenticator"
                else:
                    secret, uri = pending[userid]
                    code = str(body.get("code", "")).strip()
                    if not tfa_setup.verify(secret, code):
                        raise ValueError("that code does not match; check the key in your authenticator and try again")
                    done = deps.get("tfa_run", subprocess.run)(tfa_setup.enroll_argv(userid, uri, code, "Baseline authenticator"),
                                                              capture_output=True, text=True, timeout=60)
                    if done.returncode != 0:
                        raise ValueError("Proxmox refused the registration: " + (done.stderr or "").strip()[-120:])
                    del pending[userid]
                    notice = f"Two-factor is on for {userid}"
                    if deps.get("audit"):
                        deps["audit"]({"event": "tfa_enrolled", "userid": userid})
            except KeyError:
                notice = "start the setup first"
            except ValueError as exc:
                notice = str(exc)[:160]
            return self._redirect("/security?notice=" + html.escape(notice).replace(" ", "+"))

        if path in ("/vault/set", "/vault/unlock", "/vault/lock"):
            import vault
            notice = ""
            try:
                if path == "/vault/lock":
                    for _label, _scope, root in _vault_roots():
                        vault.Vault(root).lock(vault.RUNTIME_DIR)
                    deps.pop("vault_passphrase", None)
                    notice = "Vault locked"
                else:
                    passphrase = str(body.get("passphrase", ""))
                    if path == "/vault/set":
                        if passphrase != str(body.get("again", "")):
                            raise ValueError("the two passphrases differ")
                        for _label, _scope, root in _vault_roots():
                            store = vault.Vault(root)
                            if not store.has_passphrase():
                                store.set_passphrase(passphrase)
                    names = []
                    for _label, _scope, root in _vault_roots():
                        store = vault.Vault(root)
                        if store.has_passphrase():
                            names += store.unlock(passphrase, vault.RUNTIME_DIR)
                    deps["vault_passphrase"] = passphrase
                    notice = f"Vault unlocked for this boot ({len(names)} secrets)"
                    if deps.get("audit"):
                        deps["audit"]({"event": "vault_unlocked", "count": len(names)})
            except vault.WrongPassphrase:
                notice = "Wrong passphrase"
            except (vault.VaultError, vault.SealError, ValueError, OSError) as exc:
                notice = str(exc)[:160]
            return self._redirect("/vault?notice=" + html.escape(notice).replace(" ", "+"))

        if path.startswith("/ai-setup/"):
            import ai_setup_page
            import provider_setup
            import vault
            roots = {"admin": vault.ADMIN_VAULT, "personal": vault.PERSONAL_VAULT}
            try:
                if path == "/ai-setup/claude/start":
                    old = deps.get("claude_setup")
                    if old is not None:
                        old.cancel()
                    deps["claude_setup"] = provider_setup.GuidedSetup(
                        deps.get("claude_setup_argv") or ["claude", "setup-token"], _vault_for(deps, vault.ADMIN_VAULT),
                        "CLAUDE_CODE_OAUTH_TOKEN",
                        allowed_url_prefix=ai_setup_page.CLAUDE_URL_PREFIX)
                    deps["claude_setup"].start()
                    return self._redirect("/ai-setup/claude")
                if path == "/ai-setup/claude/code":
                    session = deps.get("claude_setup")
                    if session is None:
                        raise provider_setup.SetupError("no sign-in is in progress")
                    session.submit_code(str(body.get("code", "")))
                    return self._redirect("/ai-setup/claude")
                if path == "/ai-setup/claude/cancel":
                    if deps.get("claude_setup") is not None:
                        deps["claude_setup"].cancel()
                    return self._redirect("/ai-setup")
                if path == "/ai-setup/paste":
                    name, scope = ai_setup_page.paste_target(str(body.get("name", "")), str(body.get("scope", "")))
                    _vault_for(deps, roots[scope]).put(name, str(body.get("value", "")))
                    if deps.get("audit"):
                        deps["audit"]({"event": "vault_secret_stored", "name": name, "scope": scope})     # never the value
                    return self._redirect("/ai-setup?notice=" + html.escape(f"{name} saved to the {scope} vault"))
            except vault.VaultLocked:
                return self._redirect("/vault?notice=Unlock+the+vault+first")
            except (provider_setup.SetupError, vault.VaultError, vault.SealError, ValueError, OSError) as exc:
                return self._redirect("/ai-setup?notice=" + html.escape(str(exc))[:180].replace(" ", "+"))

        if path == "/console/switch":
            import console_switch
            if not console_switch.is_local(self.client_address[0]):
                return self._html_response(403, console_switch.refused_page())
            console_switch.switch(run=deps.get("console_run", subprocess.run))
            return self._redirect("/console")

        if path == "/host/restart":
            import host_restart
            runner = deps.get("runner")
            try:
                if runner is None:
                    raise RuntimeError("Host restart service is unavailable")
                result = host_restart.request_restart(runner)
                status = 200
            except (RuntimeError, OSError) as exc:
                result = {"outcome": "failed", "detail": str(exc)}
                status = 503
            if deps.get("audit"):
                deps["audit"]({"event": "host_restart_request", **result})
            if self._is_json_request():
                return self._json(status, result)
            return self._html_response(status, _with_nav(
                ('<html><body><h1>Host restart</h1><p>' + html.escape(result["detail"]) +
                 '</p><a href="/drive-admin">Back to Drive Administration</a></body></html>').encode(),
                "/drive-admin"))

        if path == "/login":
            if self._throttled("login", now):
                return
            accounts = deps.get("operator_accounts")
            role = accounts.authenticate(body.get("username", ""), body.get("password", "")) if accounts is not None else None
            if role is not None:
                session = deps["sessions"].create(body["username"], now, role=role)
                session.ttl_s = _operator_session_seconds(deps)
                deps["sessions"].persist(session)
                self._record_attempt("login", now, ok=True)
                return self._redirect("/operations" if session.role == "operator" else "/home", set_cookie=ws.session_cookie(session.token))
            result = sw.handle_login(deps["verifier"], deps["sessions"],
                                      body.get("username", ""), body.get("password", ""), now,
                                      persona_provider=deps.get("persona_provider"))
            if result.outcome == "applied" and body.get("username", "") in _operator_users(deps):
                operator = deps["sessions"].sessions[result.body["token"]]
                operator.role = "operator"
                operator.ttl_s = _operator_session_seconds(deps)
                deps["sessions"].persist(operator)
            self._record_attempt("login", now, ok=result.outcome == "applied")
            if result.outcome == "applied":
                role = deps["sessions"].sessions[result.body["token"]].role
                return self._redirect("/operations" if role == "operator" else "/home",
                                      set_cookie=ws.session_cookie(result.body["token"]))
            return self._html_response(401, _with_nav(sw.render_login_page("Invalid username or password."), "/login"))

        if path.startswith("/settings/"):
            section = path[len("/settings/"):]
            if self._is_json_request():
                values = body
            else:
                current = deps["source"].current_settings().get(section, {}) if deps.get("source") else {}
                values = sw.reconstruct_typed_form_values(body, list(current.keys()))
            result = sw.handle_settings_edit(deps["sessions"], deps["applier"], self._cookie_token(),
                                              section, values, now, persona_provider=deps.get("persona_provider"))
            if self._is_json_request():
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            if result.outcome == "refused" and result.status == 401:
                return self._redirect("/login")
            notice = result.body.get("detail") or result.body.get("reason", "")
            settings = deps["source"].current_settings() if deps.get("source") else {}
            return self._html_response(result.status, _with_nav(sw.render_settings_page(settings, notice), "/settings"))

        if path == "/diagnostics/iperf3/run":
            options = body if self._is_json_request() else sw.reconstruct_typed_form_values(
                body, ["role", "peer_address", "port", "bind_address"])
            result = sw.handle_iperf3_run(deps["sessions"], deps["applier"], self._cookie_token(), options, now,
                                          persona_provider=deps.get("persona_provider"))
            if deps.get("audit"):
                deps["audit"]({"event": "iperf3_request", "outcome": result.outcome, **result.body})
            if self._is_json_request():
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            settings = deps["source"].current_settings() if deps.get("source") else {}
            return self._html_response(result.status, _with_nav(sw.render_settings_page(
                settings, result.body.get("detail") or result.body.get("error", "")), "/settings"))

        if path == "/admin/elevate":
            if self._throttled("elevate", now):
                return
            result = sw.handle_admin_elevate(deps["elevation_store"], deps.get("elevation_verify_fn"),
                                              deps["sessions"], self._cookie_token(), body.get("passphrase", ""), now)
            if result.outcome == "applied" or result.body.get("error") == "invalid elevation passphrase":
                self._record_attempt("elevate", now, ok=result.outcome == "applied")
            notice = result.body.get("detail") or result.body.get("error") or result.body.get("reason", "")
            return self._redirect(f"/admin?notice={notice}")

        if path.startswith("/admin/settings/"):
            rest = path[len("/admin/settings/"):]
            group, _, key = rest.partition("/")
            values = body if self._is_json_request() else sw.reconstruct_typed_form_values(body, ["value"])
            result = sw.handle_admin_edit(deps["sessions"], deps.get("runner"), deps["elevation_store"],
                                           self._cookie_token(), group, key, values.get("value"), now)
            if self._is_json_request():
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            notice = result.body.get("detail") or result.body.get("error") or result.body.get("reason", "")
            return self._redirect(f"/admin?notice={notice}")

        if path == "/setup/machine-passphrase":
            result = sw.handle_set_machine_passphrase(deps.get("store"), body.get("passphrase", ""))
            notice = result.body.get("detail") or result.body.get("error", "")
            from urllib.parse import quote
            return self._redirect(f"/setup?notice={quote(notice)}")

        if path == "/recovery/unlock":
            if self._throttled("recovery", now):
                return
            result = sw.handle_admin_elevate(deps["recovery_store"], deps.get("recovery_verify_fn"),
                                              deps["sessions"], self._cookie_token(), body.get("passphrase", ""), now)
            if result.outcome == "applied" or result.body.get("error") == "invalid elevation passphrase":
                self._record_attempt("recovery", now, ok=result.outcome == "applied")
            return self._redirect("/recovery")

        if path == "/recovery/exit":
            if not sw.recovery_unlocked(deps, now):
                return self._redirect("/recovery")
            result = sw.handle_recovery_exit(deps.get("runner"), personas=deps.get("personas", ()), now=now)
            notice = result.body.get("detail") or result.body.get("reason", "")
            return self._redirect(f"/recovery?notice={notice}")

        if path == "/drive-admin/action":
            # A drive action never runs on request. It becomes a CHALLENGE that a person must confirm (hitl.py),
            # unless a person has granted a standing approval for exactly this action and drive.
            action_id = body.get("action_id", "")
            params = body.get("params", {})
            if not isinstance(action_id, str) or not isinstance(params, dict):
                return self._json(400, {"outcome": "refused", "detail": "refused: malformed request"})
            if not wg.role_permits(deps["sessions"].get(self._cookie_token(), now).role, "drive_action", {"action_id": action_id}):
                return self._json(403, {"outcome": "refused", "detail": "refused: this login is not authorized for that action"})
            try:
                prepared = da.prepare_action(action_id, params, pds_runner=deps.get("pds_runner"))
            except ValueError as exc:
                return self._json(400, {"outcome": "refused", "detail": str(exc)})
            store, session = _hitl_store(deps), self._cookie_token()
            authorization = store.authorization_from_grant(session, action_id, prepared["params"], prepared["serial"])
            if authorization is None:
                me = deps["sessions"].get(session, now)
                if me is not None and me.role.startswith(wg.BOT_PREFIX):
                    authorization = store.authorization_from_daily(me.username, action_id, prepared["params"], prepared["serial"])
            if authorization is not None:
                return self._start_drive_job(deps, action_id, prepared["params"], authorization, store)
            try:
                challenge = store.challenge(session, action_id, prepared["params"], prepared["serial"], prepared["summary"])
            except ValueError as exc:
                return self._json(429, {"outcome": "refused", "detail": f"refused: {exc}"})
            return self._json(200, {"outcome": "confirmation_required", "challenge": challenge})

        if path == "/drive-admin/confirm":
            if self._throttled("confirm", now):
                return
            store, session = _hitl_store(deps), self._cookie_token()
            challenge_id = body.get("challenge_id", "")
            request = store.pending_request(challenge_id) if isinstance(challenge_id, str) else None
            if request is None:
                return self._json(404, {"outcome": "refused", "detail": "that confirmation is unknown, expired or already used"})
            daily_for = None
            if body.get("daily") is True:
                me = deps["sessions"].get(session, now)
                if me is None or not me.role.startswith(wg.BOT_PREFIX):
                    return self._json(403, {"outcome": "refused", "detail": "refused: authorizing for the day is for bot accounts"})
                daily_for = me.username
            try:
                authorization = store.confirm(session, challenge_id, body.get("typed", ""), body.get("secret", ""),
                                              daily_for=daily_for)
            except hitl.ConfirmationError as exc:
                if exc.reason in ("phrase", "credential"):
                    self._record_attempt("confirm", now, ok=False)
                return self._json(403, {"outcome": "refused", "detail": f"refused: {exc}", "reason": exc.reason})
            self._record_attempt("confirm", now, ok=True)
            action_id, params, _serial = request
            return self._start_drive_job(deps, action_id, params, authorization, store)

        if path == "/drive-admin/execute-native":
            if not isinstance(body, dict) or set(body) != {"challenge_id"} or not isinstance(body["challenge_id"], str):
                return self._json(400, {"detail": "An exact drive-action permission request is required"})
            me = deps["sessions"].get(self._cookie_token(), now)
            if me is None or me.role not in ("admin", "operator"):
                return self._json(403, {"detail": "Native drive actions require an operator account"})
            store = _hitl_store(deps)
            request = store.pending_request(body["challenge_id"])
            if request is None or request[0] != "unmount_partition":
                return self._json(403, {"detail": "Native partition-unmount request expired or already used"})
            try:
                authorization = store.request_native_policykit(self._cookie_token(), body["challenge_id"])
            except hitl.ConfirmationError as exc:
                return self._json(403, {"detail": str(exc)})
            return self._start_drive_job(deps, request[0], request[1], authorization, store)

        if path == "/drive-admin/approvals":
            if self._throttled("confirm", now):
                return
            store, session = _hitl_store(deps), self._cookie_token()
            try:
                prepared = da.prepare_action(body.get("action_id", ""), {"device_path": body.get("device_path", "")},
                                             pds_runner=deps.get("pds_runner"))
                grant = store.grant(session, action_id=body.get("action_id", ""), serial=prepared["serial"],
                                    minutes=body.get("minutes"), max_uses=body.get("max_uses"),
                                    typed=body.get("typed", ""), secret=body.get("secret", ""))
            except hitl.ConfirmationError as exc:
                if exc.reason in ("phrase", "credential"):
                    self._record_attempt("confirm", now, ok=False)
                return self._json(403, {"outcome": "refused", "detail": f"refused: {exc}", "reason": exc.reason})
            except ValueError as exc:
                return self._json(400, {"outcome": "refused", "detail": str(exc)})
            self._record_attempt("confirm", now, ok=True)
            return self._json(200, {"outcome": "applied", "grant": grant})

        if path == "/drive-admin/approvals/revoke":
            store = _hitl_store(deps)
            mine = {g["id"] for g in store.list_grants(self._cookie_token())}
            gid = body.get("id", "")
            return self._json(200, {"outcome": "applied" if gid in mine and store.revoke(gid) else "refused"})

        if path.startswith("/operations/"):
            return self._post_operations(deps, path, body, now)

        if path in ("/workloads/result", "/workloads/inspect", "/workloads/acknowledge"):
            jobs=deps.get("workload_jobs")
            if jobs is None:
                return self._json(503,{"message":"durable workload storage is unavailable"})
            try:
                jid=body.get("job_id","")
                if path == "/workloads/result":
                    return self._json(200,jobs.result(jid))
                if path == "/workloads/acknowledge":
                    return self._json(200,jobs.acknowledge(jid,body.get("name","")))
                job=jobs.get(jid)
                context=job.get('context',{})
                if job['kind']=='installer' and job['action']=='update_installed_drive':
                    import installed_drive_update
                    bundle=Path(jobs.parameters(jid)['backup_id'])
                    owner=deps['sessions'].get(self._cookie_token(),now).username
                    owned=Path(deps['installer_bundle_root'])/hashlib.sha256(owner.encode()).hexdigest()
                    if bundle.parent != owned or bundle.is_symlink():
                        return self._json(403,{'message':'Update snapshot belongs to another operator'})
                    try:
                        observation=installed_drive_update.inspect_update(bundle)
                    except (installed_drive_update.UpdateError,OSError,ValueError,KeyError) as exc:
                        observation={'available':False,'message':'Native update inspection unavailable: '+str(exc)}
                    return self._json(200,jobs.inspect(jid,observation))
                if job['kind']=='installer' and job['action']=='acquire_ubuntu_source':
                    import installer_sources,installer_cache
                    try:
                        lock=installer_sources.locks(deps['runner'],deps.get('installer_cache_root',installer_cache.DEFAULT_CACHE_ROOT)).get('ubuntu_base')
                        message='Source verified on current cache filesystem.' if lock else 'No published source; acknowledge and retry acquisition.'
                        observation={'available':True,'message':message+' No installation stages ran.'}
                    except (installer_sources.SourceError,OSError) as exc:
                        observation={'available':False,'message':str(exc)+' Restore cache mount before inspecting acquisition.'}
                    return self._json(200,jobs.inspect(jid,observation))
                if job['kind']=='installer' and job['action']=='prepare_inputs':
                    import installer_inputs
                    owner=deps['sessions'].get(self._cookie_token(),now).username
                    folder=Path(deps['installer_bundle_root'])/hashlib.sha256(owner.encode()).hexdigest()/job['name']
                    try:
                        checks=installer_inputs.verify(folder)
                        observation={'available':True,'message':'Source preparation files verified; ready='+str(checks['ready'])+'. No physical installation stages ran.'}
                    except (installer_inputs.InputError,OSError,ValueError) as exc:
                        observation={'available':True,'message':'Source preparation incomplete or damaged: '+str(exc)+'. These source-only files are not usable. No physical installation stages ran; acknowledge this failed preparation and prepare a new bundle.'}
                    return self._json(200,jobs.inspect(jid,observation))
                if job['kind']=='container':
                    import distro_containers
                    host=deps.get('container_host') or (distro_containers.DistroContainers(context['data_store']) if context.get('data_store') else _container_host_for(deps))
                else:
                    import proxmox_vm_host
                    engine=proxmox_vm_host.ProxmoxVmHost if context.get('backend')=='ProxmoxVmHost' else vh.VmHost
                    host=deps.get('vm_host') or (engine(context['store'],persistence_store=context['persistence_store']) if context.get('store') else _vm_host_for(deps))
                if host is None:
                    raise workload_jobs.JobError('native backend unavailable; no inspection performed')
                if not job['name']:
                    observation={'available':True,'message':'No named workload. Check native template/cache state before acknowledging.'}
                else:
                    try:
                        state=(host.inspect_recovery(job['name']) if job['kind']=='container' and host.record(job['name']).get('phase')!='ready' else host.status(job['name']))
                        observation={'available':True,'message':json.dumps(state,default=str)}
                    except (vh.VmError,OSError,ValueError):
                        observation={'available':False,'message':'Workload inspection failed; no absence or successful recovery is inferred. Inspect Proxmox resources.'}
                return self._json(200,jobs.inspect(jid,observation))
            except (workload_jobs.JobError,ValueError,TypeError) as exc:
                return self._json(409,{'message':str(exc)})

        if path in ('/install-plan/draft', '/recipes/draft', '/install-plan/display'):
            import configuration_drafts
            store = deps.get('draft_store')
            if store is None:
                return self._json(503, {'ok':False, 'message':'Durable configuration draft storage unavailable'})
            if not isinstance(body,dict) or set(body) != {'document','revision'}:
                return self._json(400, {'ok':False,'message':'Draft requires document and revision only'})
            session = deps['sessions'].get(self._cookie_token(), now)
            kind = 'installer-display' if path == '/install-plan/display' else 'installer' if path.startswith('/install-plan') else 'recipe'
            try:
                draft = store.save(session.username, kind, body['document'], expected_revision=body['revision'])
                if deps.get('audit'):
                    deps['audit']({'event':'configuration_draft_saved','username':session.username,'kind':kind,'revision':draft['revision']})
                return self._json(200, {'ok':True, 'draft':draft})
            except configuration_drafts.DraftConflict as exc:
                return self._json(409, {'ok':False,'message':str(exc)})
            except configuration_drafts.DraftError as exc:
                return self._json(400, {'ok':False,'message':str(exc)})
            except (OSError, sqlite3.Error) as exc:
                return self._json(503, {'ok':False,'message':'Draft could not be saved: ' + str(exc)})

        if path == '/installer-cache/acquire':
            import installer_sources,installer_cache
            jobs=deps.get('workload_jobs');gate=deps.get('web_gate')
            if jobs is None or gate is None or deps.get('runner') is None:return self._json(503,{'message':'Durable native acquisition unavailable'})
            if not isinstance(body,dict) or set(body)!={'source','request_id'} or body['source']!='ubuntu_base' or not isinstance(body['request_id'],str) or not 1<=len(body['request_id'])<=64:
                return self._json(400,{'message':'Choose the supported pinned Ubuntu source and a request ID'})
            owner=deps['sessions'].get(self._cookie_token(),now).username
            identity=hashlib.sha256((owner+':'+body['request_id']).encode()).hexdigest()
            signed={'source':'ubuntu_base'}
            try:
                origin=gate.origin_for_session(deps['sessions'],self._cookie_token(),'installer_source_acquire',signed,now)
                root=deps.get('installer_cache_root',installer_cache.DEFAULT_CACHE_ROOT)
                def acquire(report):
                    wg.require(origin,'installer_source_acquire',signed)
                    report('Checking mounted INSTALLER_CACHE identity, acquiring pinned vanilla Ubuntu source, and verifying SHA256.')
                    try:lock=installer_sources.acquire_ubuntu(deps['runner'],root)
                    except (installer_sources.SourceError,OSError) as exc:return {'ok':False,'message':str(exc)}
                    return {'ok':True,'message':'Vanilla Ubuntu source verified at '+lock['path']+'. HTTPS and SHA256 verified; detached signature not verified. No VM or installation created.'}
                job=jobs.submit('installer','acquire_ubuntu_source',{'name':'ubuntu-source'},acquire,request_id='source:'+identity,with_progress=True)
                return self._json(202,{'job_id':job['id'],'state':job['state'],'executed':False})
            except (workload_jobs.JobError,wg.NotFromWebApp,ValueError) as exc:return self._json(409,{'message':str(exc)})

        if path == '/install-plan/app-config':
            import application_bundle,install_plan_page
            if not isinstance(body,dict) or set(body)!={'app','configuration'} or not isinstance(body['configuration'],dict):
                return self._json(400,{'message':'Provide an application and configuration object'})
            try:
                install_plan_page.catalog_entries(deps.get('installer_repo_root'),
                    catalog_directory=deps.get('application_catalog_root'))
                checked=application_bundle.capture(body['app'],json.dumps(body['configuration']))
                if checked['excluded_count']:raise application_bundle.er.RecipeError('Unsupported application configuration fields')
                return self._json(200,{'configuration':checked['configuration'],'applied':False})
            except (application_bundle.er.RecipeError,OSError,ValueError,KeyError,TypeError) as exc:
                return self._json(400,{'message':str(exc)})

        if path == '/install-plan/catalog':
            import application_bundle,install_plan_page
            if not isinstance(body,dict) or set(body)!={'definition'}:
                return self._json(400,{'message':'Provide a native application definition'})
            if deps['sessions'].get(self._cookie_token(),now).role not in ('admin','operator'):
                return self._json(403,{'message':'Catalog changes require an operator account'})
            try:
                definition=body['definition']
                application_bundle.validate_application_definition(definition)
                folder=deps.get('application_catalog_root') or application_bundle.application_catalog_directory()
                application_bundle.save_application_definition(folder,definition)
                application_bundle.register_application(definition)
                return self._json(201,{'registered':True,'installed':False,'id':definition['id']})
            except (application_bundle.er.RecipeError,OSError,ValueError,KeyError,TypeError) as exc:
                return self._json(400,{'message':str(exc)})

        if path == '/install-plan/execute-native':
            if not isinstance(body,dict) or set(body)!={'challenge_id'} or not isinstance(body['challenge_id'],str):
                return self._json(400,{'detail':'An exact native update challenge is required'})
            me=deps['sessions'].get(self._cookie_token(),now)
            if me.role not in ('admin','operator'):
                return self._json(403,{'detail':'Automatic native updates require an operator account'})
            store=_hitl_store(deps)
            request=store.pending_request(body['challenge_id'])
            if request is None or request[0]!='update_installed_drive':
                return self._json(403,{'detail':'Native update challenge expired or already used'})
            try:
                authorization=store.request_native_update(self._cookie_token(),body['challenge_id'])
            except hitl.ConfirmationError as exc:
                return self._json(403,{'detail':str(exc)})
            return self._start_drive_job(deps,request[0],request[1],authorization,store)

        if path in ('/install-plan/continue','/install-plan/update'):
            selected=deps.get('installer_selected_serial')
            if body.get('serial') in deps.get('installer_protected_serials',[]) or (selected and body.get('serial') != selected):
                return self._json(403,{'detail':'This drive is protected or differs from the selected installation target'})

        if path == '/install-plan/continue':
            import installer_inputs,installed_drive_update
            jobs=deps.get('workload_jobs');gate=deps.get('web_gate')
            if jobs is None or gate is None or not deps.get('installer_bundle_root'):
                return self._json(503,{'message':'Durable installer continuation unavailable'})
            if (not isinstance(body,dict) or set(body)!={'serial','request_id'}
                    or not isinstance(body['serial'],str) or not isinstance(body['request_id'],str)
                    or not 1<=len(body['request_id'])<=64):
                return self._json(400,{'message':'A selected serial and continuation request ID are required'})
            try:
                device=deps.get('installed_update_discovery',installed_drive_update.discover_path)(body['serial'])
                deps.get('installed_update_recovery',installed_drive_update.discover_recovery)(body['serial'])
                owner=deps['sessions'].get(self._cookie_token(),now).username
                drafts=deps.get('draft_store')
                draft=drafts.get(owner,'installer') if drafts else None
                recipe=drafts.get(owner,'recipe') if drafts else None
                plan=draft['document'] if draft else {'installed_update':{'serial':body['serial']}}
                settings=deps['source'].current_settings() if deps.get('source') else {}
                settings={key:value for key,value in settings.items() if not key.startswith('_')}
                identity=hashlib.sha256(json.dumps({'owner':owner,'serial':body['serial'],
                    'request':body['request_id']},sort_keys=True).encode()).hexdigest()
                name=identity[:32]
                folder=Path(deps['installer_bundle_root'])/hashlib.sha256(owner.encode()).hexdigest()/name
                signed={'serial':body['serial'],'bundle':name,'device_path':device}
                origin=gate.origin_for_session(deps['sessions'],self._cookie_token(),'installer_prepare_inputs',signed,now)
                root=Path(deps.get('installer_repo_root') or Path(__file__).resolve().parents[2])
                def capture(report):
                    wg.require(origin,'installer_prepare_inputs',signed)
                    report('Automatically capturing current source and existing configuration; no physical writes.')
                    installer_inputs.prepare(root,folder,plan=plan,settings=settings,
                        recipe=recipe['document'] if recipe else None,artifact_locks={})
                    installer_inputs.verify(folder)
                    return {'ok':True,'message':'Existing-installation update inputs captured and integrity checked. '
                        'Online target package provisioning still requires native authorization; no new installation or workload was created.'}
                job=jobs.submit('installer','prepare_inputs',{'name':name},capture,
                    request_id='update-inputs:'+identity,with_progress=True)
                return self._json(202,{'job_id':job['id'],'state':job['state'],'executed':False})
            except (installed_drive_update.UpdateError,installer_inputs.InputError,workload_jobs.JobError,
                    wg.NotFromWebApp,OSError,ValueError) as exc:
                return self._json(409,{'message':str(exc),'executed':False})

        if path == '/install-plan/update':
            import installer_inputs,installed_drive_update
            jobs=deps.get('workload_jobs')
            if jobs is None or not deps.get('installer_bundle_root'):
                return self._json(503,{'outcome':'refused','detail':'Durable installer inputs unavailable'})
            if (not isinstance(body,dict) or set(body)!={'serial','job_id'}
                    or not isinstance(body['serial'],str) or not isinstance(body['job_id'],str)):
                return self._json(400,{'outcome':'refused','detail':'Select a serial and completed preparation job'})
            try:
                job=jobs.get(body['job_id'])
                if (job['kind'],job['action'],job['state'])!=('installer','prepare_inputs','completed'):
                    raise installer_inputs.InputError('A completed preparation job is required')
                owner=deps['sessions'].get(self._cookie_token(),now).username
                folder=Path(deps['installer_bundle_root'])/hashlib.sha256(owner.encode()).hexdigest()/job['name']
                installer_inputs.verify(folder)
                device=deps.get('installed_update_discovery',installed_drive_update.discover_path)(body['serial'])
                recovery=deps.get('installed_update_recovery',installed_drive_update.discover_recovery)(body['serial'])
                prepared=da.prepare_action('update_installed_drive',{'device_path':device,
                    'input_bundle':str(folder),'recovery_folder':str(recovery)},pds_runner=deps.get('pds_runner'))
                challenge=_hitl_store(deps).challenge(self._cookie_token(),'update_installed_drive',
                    prepared['params'],prepared['serial'],prepared['summary'])
                return self._json(200,{'outcome':'confirmation_required','challenge':challenge})
            except (installer_inputs.InputError,installed_drive_update.UpdateError,workload_jobs.JobError,
                    pds.PhysicalDeviceSafetyError,OSError,ValueError) as exc:
                return self._json(409,{'outcome':'refused','detail':str(exc)})

        if path == '/install-plan/prepare-inputs':
            import installer_inputs
            drafts=deps.get('draft_store');jobs=deps.get('workload_jobs');gate=deps.get('web_gate')
            if drafts is None or jobs is None or gate is None or not deps.get('installer_bundle_root'):
                return self._json(503,{'message':'Durable installer preparation unavailable'})
            if not isinstance(body,dict) or set(body)!={'revision','request_id'} or type(body['revision']) is not int or not isinstance(body['request_id'],str) or not 1<=len(body['request_id'])<=64:
                return self._json(400,{'message':'Installer preparation requires saved draft revision and request ID'})
            owner=deps['sessions'].get(self._cookie_token(),now).username
            try:
                draft=drafts.get(owner,'installer')
                if draft is None or draft['revision']!=body['revision']:
                    return self._json(409,{'message':'Save/reload the current installer draft before preparing inputs'})
                recipe=drafts.get(owner,'recipe')
                settings=deps['source'].current_settings() if deps.get('source') else {}
                settings={key:value for key,value in settings.items() if not key.startswith('_')}
                plan=draft['document']
                source_locks=dict(deps.get('installer_artifact_locks',{}));source_errors=[]
                if deps.get('installer_cache_root') and deps.get('runner'):
                    import installer_sources
                    try:source_locks.update(installer_sources.locks(deps['runner'],deps['installer_cache_root']))
                    except (installer_sources.SourceError,OSError) as exc:source_errors.append(str(exc))
                recipe_document=recipe['document'] if recipe else None
                identity=hashlib.sha256(json.dumps({'owner':owner,'request':body['request_id'],'revision':body['revision']},sort_keys=True).encode()).hexdigest()
                name=identity[:32]
                folder=Path(deps['installer_bundle_root'])/hashlib.sha256(owner.encode()).hexdigest()/name
                signed={'revision':draft['revision'],'bundle':name}
                origin=gate.origin_for_session(deps['sessions'],self._cookie_token(),'installer_prepare_inputs',signed,now)
                root=Path(deps.get('installer_repo_root') or Path(__file__).resolve().parents[2])
                def prepare_inputs(report):
                    wg.require(origin,'installer_prepare_inputs',signed)
                    report('Capturing current code, saved configuration and source/dependency checks. No physical stages run.')
                    result=installer_inputs.prepare(root,folder,plan=plan,settings=settings,recipe=recipe_document,artifact_locks=source_locks,source_errors=source_errors)
                    installer_inputs.verify(folder)
                    message='Installer inputs prepared and integrity checked. '
                    message+='Ready for the next execution preflight.' if result['ready'] else 'Not ready to install: '+ '; '.join(result['errors'])
                    return {'ok':True,'message':message}
                job=jobs.submit('installer','prepare_inputs',{'name':name},prepare_inputs,
                    request_id='installer-inputs:'+identity,with_progress=True)
                return self._json(202,{'job_id':job['id'],'state':job['state'],'executed':False})
            except (workload_jobs.JobError,installer_inputs.InputError,wg.NotFromWebApp,OSError,ValueError) as exc:
                return self._json(409,{'message':str(exc),'executed':False})

        if path == "/install-plan/action":
            import install_plan_page, install_plan
            try:
                provider=deps.get("install_plan_discovery",install_plan_page.discover_current)
                return self._json(200,install_plan_page.perform(body,discovery_provider=provider))
            except install_plan.PlanError as exc:
                return self._json(400,{"ok":False,"executed":False,"message":str(exc),"errors":exc.errors})

        if path == "/recipes/action":
            import recipe_page, environment_recipes
            try:
                return self._json(200,recipe_page.perform(body))
            except environment_recipes.RecipeError as exc:
                return self._json(400,{'ok':False,'message':str(exc)})

        if path in ("/containers/action", "/vms/action"):
            jobs=deps.get('workload_jobs')
            if jobs is None:
                return self._json(503,{'ok':False,'message':'durable workload storage is not configured'})
            action=str(body.get('action',''))
            kind='container' if path=='/containers/action' else 'vm'
            # Capture the backend/storage at submission. Changing defaults is refused while work needs review.
            try:
                host=_container_host_for(deps) if kind=='container' else _vm_host_for(deps)
            except (vh.VmError, OSError, ValueError) as exc:
                return self._json(503,{'ok':False,'message':f'Native workload storage configuration unavailable: {exc}'})
            if host is None:
                return self._json(503,{'ok':False,'message':'native backend unavailable'})
            if action in ('set_data','set_store'):
                if any(j['state'] in ('queued','running','interrupted') for j in jobs.listing()):
                    return self._json(409,{'ok':False,'message':'finish or inspect the workload job before changing storage'})
                import container_page
                result=container_page.save_data(deps.get('vm_config_path'),body.get('data_store')) if kind=='container' else \
                    vm_page.save_store(deps.get('vm_config_path'),body.get('store'),persistence_store=body.get('persistence_store'))
                return self._json(200,result)
            actions={'container':{'create','start','shutdown','rebuild','refresh','reset_login','recover','backup','restore'},
                     'vm':{'prepare_ubuntu','create_ubuntu','create_iso','create_overlay','start','request_stop','force_stop',
                           'configure','eject_iso','rollback','freeze','delete_vm','delete_base','reset_login','inspect_app','verify_ubuntu'}}
            if action not in actions[kind]:
                return self._json(400,{'ok':False,'message':'unknown workload action'})
            params={k:v for k,v in body.items() if k not in ('action','request_id')}
            origin=None
            if kind=='container' and action in ('backup','restore'):
                gate=deps.get('web_gate')
                if gate is None:return self._json(503,{'ok':False,'message':'web backup authorization unavailable'})
                keys=('name','destination','backup_id') if action=='restore' else ('name','destination')
                signed={key:str(params.get(key,'')) for key in keys}
                origin=gate.origin_for_session(deps['sessions'],self._cookie_token(),'container_'+action,signed,now)
            def execute(report):
                import container_page
                original_run=host.run
                def traced_run(args,*extra,**kw):
                    report('Native command: ' + ' '.join(str(a) for a in args[:2]))
                    return original_run(args,*extra,**kw)
                host.run=traced_run
                try:
                    result=container_page.perform(host,action,params,origin=origin,backup_run=deps.get('container_backup_run')) if kind=='container' else \
                        vm_page.perform(host,action,params,iso_dir=deps.get('vm_iso_dir') or vh.DEFAULT_ISO_DIR)
                finally:
                    host.run=original_run
                audit=deps.get('audit')
                if audit:
                    audit({'event':kind+'_action','action':action,'name':str(params.get('name','')),'ok':result['ok']})
                return result
            try:
                context={'data_store':str(host.data_store),'backend':type(host).__name__} if kind=='container' else \
                    {'store':str(host.store),'persistence_store':str(host.persistence_store),'backend':type(host).__name__}
                job=jobs.submit(kind,action,params,execute,request_id=body.get('request_id'),with_progress=True,context=context)
            except workload_jobs.JobError as exc:
                return self._json(409,{'ok':False,'message':str(exc)})
            return self._json(202,{'ok':True,'job_id':job['id'],'message':'Operation recorded; follow its actual outcome in Workload jobs.'})

        if path == "/approvals/daily/revoke":
            gone = _hitl_store(deps).revoke_daily(body.get("id", "")) if isinstance(body.get("id", ""), str) else False
            return self._json(200 if gone else 404, {"outcome": "applied" if gone else "refused"})

        if path in ("/operators/add", "/operators/remove"):
            return self._post_operators(deps, path, body, now)

        if path == "/api/backup":
            gate = deps.get("web_gate")
            if gate is None:
                return self._json(503, {"outcome": "refused", "detail": "refused: no web gate on this server"})
            origin = gate.origin_for_session(deps["sessions"], self._cookie_token(), "cpw_backup", {}, now)
            result = cpw.handle_backup(deps["runner"], dest=body.get("dest", ""),
                                        targets=body.get("targets", []), config_only=bool(body.get("config_only")),
                                        now=time.time(), origin=origin)
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        result = {"outcome": "handed_off", "reason": f"no route for {path!r}"}
        self._json(404, result)


def make_server(*, deps: dict, host: str = "127.0.0.1", port: int = 8200) -> http.server.HTTPServer:
    if deps.get('workload_jobs') is None and deps.get('vm_config_path'):
        deps['workload_jobs']=workload_jobs.WorkloadJobs(Path(deps['vm_config_path']).parent/'workload-jobs.sqlite')
    server = http.server.ThreadingHTTPServer((host, port), UnifiedHandler)
    server.deps = deps  # type: ignore[attr-defined]
    original_close=server.server_close
    def close():
        original_close()
        if deps.get('workload_jobs'):
            deps['workload_jobs'].close()
    server.server_close=close
    return server


def build_real_server(host: str = "0.0.0.0", port: int = 8100, data_path=None,
                       elevation_username: str = "root", state_dir=None) -> http.server.HTTPServer:
    """The real, systemd-launched merged app.

    Drive Administration does **not** use `elevation_verify_fn` at all
    (decision record 84) - it authenticates via real `pkexec`
    (`drive_admin.PkexecRunner`, decision record 2026-09-29), whose
    own PolicyKit agent handles the operator's password entirely
    outside this app, so this app never needs to already be running
    as root - real self-elevation, not a pre-elevated process.
    `deps["pkexec_executor"]` is left unset here (`None`), which
    `PkexecRunner` already treats as "use the real `subprocess.run`" -
    only tests inject a fake one.

    `elevation_username` (default `"root"`) and
    `settings_web.SystemElevationVerifier` remain real and in use for
    the separate Admin tab's own settings-editing gate
    (`handle_admin_edit`, decision record 80) - a different, lighter
    check for a different, lighter class of change than Drive
    Administration's real destructive actions."""
    from repair import RealRunner

    runner = RealRunner()
    # The signing key lives in a root-only file. Everything that proves "the web application did this" or "this
    # credential row is genuine" is derived from it, with a different label for each purpose.
    state = Path(state_dir or DEFAULT_STATE_DIR)
    audit = hitl.AuditFile(state / "audit" / "web-actions.jsonl")
    root_key = wg.load_or_create_key(state / "web-signing.key")
    tamper_alerts: list = []

    def on_tamper(alert: dict) -> None:
        tamper_alerts.append(alert)
        audit({"event": "integrity_failure", **alert})

    settings_server = sw.build_real_server(bind_host="127.0.0.1", bind_port=0,
                                            data_path=data_path or Path("/var/lib/baseline/settings-web/store.json"),
                                            runner=runner, store_mac_key=wg.derive_key(root_key, "settings-store"),
                                            store_mac_marker=state / "settings-store.initialized", on_tamper=on_tamper)
    deps = dict(settings_server.deps)
    deps["sessions"] = sw.SessionStore(path=state / "sessions.sqlite",mac_key=wg.derive_key(root_key,"login-sessions"))
    deps["vg_name"] = drive_installer.DEFAULT_VG_NAME
    deps["config_path"] = cpw.DEFAULT_CONFIG_PATH
    deps["network_interface"] = "eno1"
    deps["pds_runner"] = pds.Runner()
    # Operations: only the web service holds the signing key (root-only file); nothing else can ask for one to run.
    audit_path = state / "audit" / "web-actions.jsonl"
    gate = wg.WebGate(wg.derive_key(root_key, "web-gate"), audit=audit)
    wg.configure(gate)
    deps["web_gate"] = gate
    deps["audit"] = audit
    deps["operator_accounts"] = operator_accounts.OperatorAccounts(
        state / "operators.json", mac_key=wg.derive_key(root_key, "operator-accounts"), on_tamper=on_tamper)
    deps["tamper_alerts"] = tamper_alerts
    deps["vm_config_path"] = state / "vm-config.json"
    import configuration_drafts
    deps["draft_store"] = configuration_drafts.DraftStore(state / "configuration-drafts.sqlite")
    deps["installer_bundle_root"] = state / "installer-inputs"
    deps["application_catalog_root"] = state / "application-definitions"
    deps["installer_selected_serial"] = os.environ.get('BASELINE_INSTALLER_SELECTED_SERIAL','')
    deps["installer_protected_serials"] = [s for s in os.environ.get('BASELINE_INSTALLER_PROTECTED_SERIALS','').split(',') if s]
    import installer_cache
    deps["installer_cache_root"] = installer_cache.DEFAULT_CACHE_ROOT
    import installer_inputs
    try:
        deps["installer_repo_root"] = installer_inputs.source_root(__file__)
    except installer_inputs.InputError:
        deps["installer_repo_root"] = None
    deps["scheduler"] = ops.Scheduler(
        gate, ops.ScheduleStore(state / "schedules.json"),
        lambda op, params, origin: _start_operation_job(deps, op, params, origin))
    import settings_store
    deps["operator_users"] = lambda: settings_store.get_setting("access", "operator_users")
    deps["operator_session_hours"] = lambda: settings_store.get_setting("access", "operator_session_hours")
    deps["hitl_audit_path"] = audit_path
    deps["audit_log_path"] = audit_path
    deps["elevation_verify_fn"] = sw.SystemElevationVerifier(elevation_username)
    # Recovery mode: this machine's root password (or its passphrase), checked
    # against the system's own one-way hash. Its own ticket store; Admin
    # elevation never opens recovery.
    import admin_elevation
    deps["recovery_store"] = admin_elevation.ElevationStore()
    deps["recovery_verify_fn"] = sw.AnyCredentialVerifier(
        sw.MachinePassphraseVerifier(deps["store"]), sw.SystemElevationVerifier("root"))
    settings_server.httpd.server_close()
    return make_server(deps=deps, host=host, port=port)


def resolve_state_dir(env, system_dir: Path = DEFAULT_STATE_DIR, writable=None) -> Path:
    """System state dir when this process may write it (installed service); otherwise the user's own directory, so
    the app runs from a desktop launcher without elevation."""
    import os
    if env.get("BASELINE_STATE_DIR"):
        return Path(env["BASELINE_STATE_DIR"])
    writable = writable or (lambda p: os.access(p, os.W_OK) if p.exists() else os.access(p.parent, os.W_OK))
    if writable(system_dir):
        return system_dir
    return Path(env.get("HOME") or os.path.expanduser("~")) / ".local" / "share" / "baseline"


def main() -> int:
    import os
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8100
    host = os.environ.get("BASELINE_WEB_BIND_HOST", "0.0.0.0")
    data_path = sw.resolve_data_path(os.environ)
    server = build_real_server(host=host, port=port, data_path=data_path, state_dir=resolve_state_dir(os.environ))
    print(f"Baseline web app on http://{host}:{port}/  (login: this machine's account password)")
    print(f"Data store: {data_path}")
    server.deps["scheduler"].start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
