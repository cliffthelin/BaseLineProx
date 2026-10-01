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
import http.server
import json
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import control_panel_web as cpw
import drive_admin as da
import drive_installer
import physical_device_safety as pds
import settings_web as sw
import hitl
import operations as ops
import operations_page
import operator_accounts
import web_gate as wg
import web_security as ws

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError


NAV_TABS = (
    ("/settings", "Settings"),
    ("/admin", "Admin"),
    ("/recovery", "Recovery"),
    ("/drive-admin", "Drive Administration"),
    ("/operations", "Operations"),
    ("/operators", "Operators"),
    ("/hardware", "Hardware"),
    ("/installer-cache", "Installer Cache"),
    ("/app-isolation", "App Isolation"),
    ("/master-config", "Master Config"),
)


def render_nav(active_path: str) -> str:
    links = "".join(
        f'<a href="{path}" class="{"active" if active_path.startswith(path) else ""}">{label}</a>'
        for path, label in NAV_TABS
    )
    return f'<nav class="baseline-nav">{links} <a href="/logout">Log out</a></nav>'


def _with_nav(body_bytes: bytes, active_path: str) -> bytes:
    """Inserts the shared nav bar right after the opening `<body...>`
    tag of an existing rendered page, without touching the already-
    tested render functions that produced it."""
    html = body_bytes.decode()
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
                             notice_ok: bool | None = None, acted_on_path: str | None = None) -> bytes:
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
    else:
        drive_cards = '<p class="empty-note">No real candidate drives found (or the enumeration failed) - nothing selectable right now.</p>'

    if volumes:
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

        volume_rows = "".join(f"""
<tr class="volume-row" data-volume-idx="{i}">
  <td><input type="checkbox" class="volume-select" value="{v['label']}"></td>
  <td>{v['label']}</td><td class="mono">{v['mountpoint']}</td><td class="mono">{_usage_text(v)}</td>
</tr>
<tr class="volume-detail-row" data-volume-idx="{i}" hidden>
  <td></td><td colspan="3" class="mono">Partition (LVM logical volume): {_lv_text(v)}</td>
</tr>""" for i, v in enumerate(volumes))
        volumes_html = f"""<table class="volume-table">
<tr><th><input type="checkbox" id="volumeSelectAll"></th><th>Volume</th><th>Mountpoint</th><th>Used</th></tr>{volume_rows}</table>
<p class="hint">Click a row to see its real partition (LVM logical volume) name and allocated size.</p>"""
    else:
        volumes_html = '<p class="empty-note">No volumes planned, or the real enumeration failed.</p>'

    action_cards = "".join(f"""
<div class="action-card {'danger' if 'PERMANENTLY ERASE' in a['description'] else ''}" data-action-card-id="{a['action_id']}"
     {'hidden' if a['action_id'] == 'update_selected' else ''}>
  <div class="action-id">{a['action_id']}</div>
  <div class="action-desc">{a['description']}</div>
  <button type="button" class="drive-admin-action" data-action-id="{a['action_id']}" data-description="{a['description']}">Run&hellip;</button>
</div>""" for a in actions)

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Drive Administration</title><style>{_DRIVE_ADMIN_CSS}</style></head>
<body>
<h1>Drive Administration</h1>
<p class="subtitle">Every real, non-boot drive attached to this machine. The pre-authorized drive is selected by default - pick any other to target it instead.</p>
{notice_html}

<h2 class="section-title">Physical drives</h2>
{drive_cards}

<h2 class="section-title">Volumes</h2>
<p class="subtitle">Select one or more volumes here, then use the Update action to check for and apply updates. Update only appears when a Baseline drive is selected above.</p>
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
    document.querySelectorAll(".volume-select").forEach(cb => {{ cb.checked = volumeSelectAll.checked; }});
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
  return Array.from(document.querySelectorAll(".volume-select:checked")).map(cb => cb.value);
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
  const selectedText = selected.length ? selected.join(", ") : "(none selected above)";
  return `<p>Checking for updates on: ${{selectedText}}</p>`;
}}

function mountVolumeParamsHtml() {{
  return `<label>Logical volume name (as it exists in the drive's real volume group)
      <input id="paramLvName" value="root"></label>
    <label>Mountpoint (leave blank for the default: /mnt/&lt;vg&gt;-&lt;lv&gt;-inspect)
      <input id="paramMountpoint" placeholder="/mnt/pve-root-inspect"></label>`;
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
function askForConfirmation(challenge) {{
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
        body: JSON.stringify({{challenge_id: challenge.id, typed: typed.value, secret: secret.value}}),
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
    box.append(summary, lead, typed, secret, msg, ok, cancel);
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


def real_drive_state(runner, *, pds_runner=None) -> list:
    """Every real, non-boot candidate drive - reuses
    `drive_admin.list_candidate_drives` directly, never a second,
    separate enumeration. The pre-authorized drive(s) come back
    pre-marked `is_default`; every other real drive is listed and
    selectable too - "not locked to just that drive" (direct
    instruction)."""
    if runner is None:
        return []
    return da.list_candidate_drives(runner, pds_runner=pds_runner)


def real_volume_state(runner) -> list:
    """Every planned volume (direct feedback: the old version only
    ever showed whatever happened to already be mounted, silently
    hiding INSTALLER_CACHE/SESSION_TEMP/SUBSTRATE/persona
    volumes that simply hadn't been created yet - "makes no sense").
    Includes each volume's real LVM identity (name, real allocated
    size) alongside its live usage when mounted."""
    if runner is None:
        return []
    try:
        details = drive_installer.collect_volume_details(runner)
    except Exception:
        return []
    return [{
        "label": d.label, "mountpoint": d.mountpoint, "lv_name": d.lv_name,
        "lv_exists": d.lv_exists, "lv_size_bytes": d.lv_size_bytes,
        "total_bytes": d.total_bytes, "used_bytes": d.used_bytes, "percent_used": d.percent_used,
    } for d in details]


def _collect_system_info(runner) -> dict:
    """Read CPU, memory, kernel from /proc and uname."""
    info = {}
    try:
        proc = runner.run(["uname", "-r"], timeout=5)
        info["kernel"] = proc.stdout.strip() if proc.returncode == 0 else "Linux"
    except Exception:
        info["kernel"] = "Linux"
    try:
        info["distro"] = runner.read_text("/etc/os-release").split("PRETTY_NAME=")[1].split("\n")[0].strip('"')
    except Exception:
        info["distro"] = "Linux"
    try:
        cpuinfo = runner.read_text("/proc/cpuinfo")
        for line in cpuinfo.splitlines():
            if line.startswith("model name"):
                info["cpu_model"] = line.split(":", 1)[1].strip()
                break
        cores = sum(1 for l in cpuinfo.splitlines() if l.startswith("processor"))
        info["cpu_cores"] = str(cores)
    except Exception:
        pass
    try:
        meminfo = runner.read_text("/proc/meminfo")
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                info["mem_total"] = f"{kb // 1048576} GiB ({kb // 1024} MiB)"
            elif line.startswith("MemAvailable:"):
                kb = int(line.split()[1])
                info["mem_available"] = f"{kb // 1048576} GiB ({kb // 1024} MiB)"
    except Exception:
        pass
    try:
        proc = runner.run(["ip", "-o", "route", "show", "default"], timeout=5)
        if proc.returncode == 0 and "dev " in proc.stdout:
            info["default_iface"] = proc.stdout.split("dev ")[1].split()[0]
    except Exception:
        pass
    return info


def real_hardware_state(runner) -> dict:
    """Real dependency-check results plus real sensor/NVMe/SMART
    facts and system info from /proc."""
    if runner is None:
        return {"dependency_results": [], "sensors": None, "nvme": None, "smart": None,
                "sysinfo": {}, "inventory": {}}
    import dependencies as dep
    import diagnostics
    import hardware_inventory as hwinv
    try:
        dep_results = [{"id": r.id, "ok": r.ok, "detail": r.detail} for r in dep.run_checks(phase=dep.ADHOC)]
    except Exception:
        dep_results = []
    try:
        sensors = diagnostics.collect_sensors(runner)
    except Exception:
        sensors = None
    try:
        nvme = diagnostics.collect_nvme(runner)
    except Exception:
        nvme = None
    try:
        smart = diagnostics.collect_smart(runner)
    except Exception:
        smart = None
    sysinfo = _collect_system_info(runner)
    try:
        inventory = hwinv.collect_all(runner)
    except Exception:
        inventory = {}
    return {"dependency_results": dep_results, "sensors": sensors, "nvme": nvme,
            "smart": smart, "sysinfo": sysinfo, "inventory": inventory}


def render_app_isolation_page(persona: str, plans: list, *,
                              leaks: list, conflicts: list, formats: list) -> bytes:
    """Per-application AppData isolation (appdata.py), shown rather than
    asserted only in tests: every app's own data tree, registry, owner
    and overlays, plus what each package format does and does not
    provide on its own.

    This page is read-only by construction - appdata.py plans, it never
    mounts. Applying a plan is privileged and belongs behind an explicit
    operator-authorized action, not a page view."""
    import appdata

    with_data = [p for p in plans if p.app.has_persistent_data or p.overlays or p.binds]
    total_overlays = sum(len(p.overlays) + len(p.binds) for p in plans)
    guarantees_hold = not leaks and not conflicts and all(p.isolated for p in plans)

    verdict = (
        '<div class="ic-banner ok"><strong>Isolation holds.</strong> '
        'No application\'s writable layer falls inside another\'s tree, no two '
        'applications claim the same overlay target, and every plan keeps its '
        'data, registry and owner inside its own AppData home.</div>'
        if guarantees_hold else
        f'<div class="ic-banner warn"><strong>Isolation violated.</strong> '
        f'{len(leaks)} cross-app leak(s), {len(conflicts)} target conflict(s). '
        f'This must be empty before any plan is applied.</div>'
    )

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
    for plan in sorted(plans, key=lambda p: (not (p.overlays or p.binds), p.app.app_id)):
        if plan.binds:
            overlay_html = "<br>".join(
                f'<span class="ov-upper">{b.host}</span>'
                f'<span class="ov-arrow"> &rArr; </span>'
                f'<span class="ov-target">{b.container}</span>'
                f'{" <span class=ov-none>(read-only)</span>" if b.read_only else ""}'
                for b in plan.binds
            ) + (f'<br><span class="ov-none">bind mounts into the container &middot; '
                 f'image {plan.app.image_ref or "NOT PINNED"}</span>')
        elif plan.overlays:
            overlay_html = "<br>".join(
                f'<span class="ov-target">{o.target}</span>'
                f'<span class="ov-arrow"> &rarr; </span>'
                f'<span class="ov-upper">{o.upperdir}</span>'
                for o in plan.overlays
            )
        else:
            overlay_html = ('<span class="ov-none">no persistent data &mdash; '
                            'no overlay (stated, not assumed)</span>')
        app_rows.append(
            "<tr>"
            f"<td>{plan.app.app_id}</td>"
            f"<td>{plan.app.kind}</td>"
            f"<td>{overlay_html}</td>"
            f"<td>{plan.registry_db}</td>"
            f"<td>{plan.owner_user}<br><span class='ov-none'>mode {plan.mode}</span></td>"
            "</tr>"
        )

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
{stats}

<h2 class="section-title">Applications <span class="ic-count">{len(plans)}</span></h2>
<p class="hw-note">Planned, not applied. Each overlay keeps the installed base
immutable as its lower layer and sends every write to the app's own upper layer
on AppData. Applying these mounts is privileged and is not done from this page.</p>
<table class="hw-table"><thead><tr><th>Application</th><th>Kind</th>
<th>Overlay (target &rarr; personal writable layer)</th><th>Own registry</th>
<th>Owner / mode</th></tr></thead><tbody>{''.join(app_rows)}</tbody></table>

<h2 class="section-title">Package formats</h2>
<p class="hw-note">Baseline never duplicates a sandbox a format already provides &mdash;
two permission models that can disagree is worse than one. Where a format brings its
own confinement, only AppData placement is added; where it brings none, Baseline
supplies the whole gap.</p>
<table class="hw-table"><thead><tr><th>Format</th><th>Own sandbox</th>
<th>Isolation mechanism</th><th>Per-app data convention</th>
<th>Baseline must supply</th></tr></thead><tbody>{fmt_rows}</tbody></table>
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
            "<tr>"
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

{banner}
{stats}
{''.join(sections)}
</body></html>""".encode()


def _render_inventory(inventory: dict) -> str:
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

    parts = []

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
                [[d.address, d.model, d.vendor,
                  f'<span class="{"drv-none" if d.kernel_driver is None else "drv-ok"}">{d.driver_status}</span>']
                 for d in devices],
            ))

    block = inventory.get("block") or []
    if block:
        parts.append(f'<h2 class="section-title">Storage Devices ({len(block)})</h2>')
        parts.append(_rows(
            ["Device", "Size", "Bus", "Model", "Serial"],
            [[f"/dev/{d.name}", d.size, d.transport or "-", d.model or "-", d.serial or "-"] for d in block],
        ))

    net = inventory.get("net") or []
    if net:
        parts.append(f'<h2 class="section-title">Network Interfaces ({len(net)})</h2>')
        parts.append(_rows(
            ["Interface", "State", "MAC"],
            [[n.name,
              f'<span class="{"drv-ok" if n.state == "UP" else "drv-none"}">{n.state}</span>',
              n.mac or "-"] for n in net],
        ))

    usb = inventory.get("usb") or []
    if usb:
        parts.append(f'<h2 class="section-title">USB Devices ({len(usb)})</h2>')
        parts.append(_rows(
            ["Bus:Dev", "ID", "Description"],
            [[f"{d.bus}:{d.device}", d.usb_id, d.description or "-"] for d in usb],
        ))

    return "".join(parts)


def render_hardware_page(*, dependency_results: list, sensors=None, nvme=None, smart=None,
                         sysinfo=None, inventory=None) -> bytes:
    """Real, direct-report page - no button, no action, just current
    state (direct instruction: run_health_check's dependency results
    plus real hardware facts, always shown, not triggered).

    A collector that is absent or reports `available=False` is stated
    as "Not available" with the real reason it gave - never silently
    dropped, which would read as "this machine has no NVMe" when the
    truth is "nvme-cli isn't installed"."""
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

    hw_html_parts.append('<h2 class="section-title">System</h2><div class="hw-card">')
    hw_html_parts.append(_hw_detail("Kernel", sysinfo.get("kernel")))
    hw_html_parts.append(_hw_detail("Distro", sysinfo.get("distro")))
    hw_html_parts.append('</div>')

    hw_html_parts.append('<h2 class="section-title">Processor (CPU)</h2><div class="hw-card">')
    hw_html_parts.append(_hw_detail("Model", sysinfo.get("cpu_model")))
    hw_html_parts.append(_hw_detail("Cores", sysinfo.get("cpu_cores")))
    hw_html_parts.append('<p class="hw-setting">📦 <strong>Setting:</strong> CPU microcode auto-installed during setup</p>')
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
            hw_html_parts.append('<p class="hw-setting">🔍 <strong>Settings:</strong> SMART monitoring (device, test schedule), health checks enabled</p>')
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

    hw_html_parts.append(_render_inventory(inventory or {}))

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
<p class="subtitle">Detected system hardware and applicable Baseline settings</p>

<h2 class="section-title">Health Checks</h2>
<div class="action-grid">{dep_html}</div>

{hw_section}
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


def _start_operation_job(deps: dict, op_id: str, params: dict, origin) -> str:
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _JOBS[job_id] = {"lines": [], "done": False, "outcome": None, "detail": None}
    threading.Thread(target=_run_operation_job, args=(job_id, op_id, params, origin, deps), daemon=True).start()
    return job_id


DEFAULT_STATE_DIR = Path("/var/lib/baseline")     # audit log, signing key and schedules (root-only, mode 0600)

# The only routes reachable without a session: the login screen itself.
_PUBLIC_PATHS = frozenset({"/", "/login", "/logout"})


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
        raw = self._read_body_bytes()
        try:
            return json.loads(raw.decode()) if raw else {}
        except ValueError:
            return {}

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
                return self._redirect("/operations" if session.role == "operator" else "/settings")
            return self._html_response(200, sw.render_login_page())

        if path == "/logout":
            return self._redirect("/login", set_cookie=ws.clear_session_cookie())

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
                formats=appdata.supported_formats()), path))

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
                                        scanned_ok=False)
            else:
                report = ic.reconcile(scan_runner)
            return self._html_response(200, _with_nav(
                render_installer_cache_page(report, elevated=elevated), path))

        if path == "/operators":
            accounts = deps.get("operator_accounts")
            return self._html_response(200, _with_nav(
                operations_page.render_operators_page(accounts.roles() if accounts else {}), path))

        if path == "/operations":
            scheduler = deps.get("scheduler")
            return self._html_response(200, _with_nav(
                operations_page.render_operations_page(ops.OPERATIONS, scheduler.listing() if scheduler else []), path))

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
            drives = real_drive_state(runner, pds_runner=deps.get("pds_runner"))
            volumes = real_volume_state(runner) if runner is not None else []
            notice = qs.get("notice", [""])[0]
            notice_ok = qs.get("ok", [None])[0]
            notice_ok = {"1": True, "0": False}.get(notice_ok)  # None when no action just ran at all
            acted_on_path = qs.get("device", [None])[0]  # which drive card an action just targeted, if any
            return self._html_response(200, _with_nav(
                render_drive_admin_page(drives=drives, volumes=volumes, actions=da.describe_actions(),
                                         notice=notice, notice_ok=notice_ok, acted_on_path=acted_on_path), path))

        if path.startswith("/hardware"):
            runner = deps.get("runner")
            state = real_hardware_state(runner)
            return self._html_response(200, _with_nav(render_hardware_page(**state), path))

        if path.startswith("/master-config"):
            return self._html_response(200, _with_nav(cpw.render_index_page().encode(), path))

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

        body = self._read_request_body()

        if path == "/login":
            if self._throttled("login", now):
                return
            accounts = deps.get("operator_accounts")
            role = accounts.authenticate(body.get("username", ""), body.get("password", "")) if accounts is not None else None
            if role is not None:
                session = deps["sessions"].create(body["username"], now, role=role)
                session.ttl_s = _operator_session_seconds(deps)
                self._record_attempt("login", now, ok=True)
                return self._redirect("/operations", set_cookie=ws.session_cookie(session.token))
            result = sw.handle_login(deps["verifier"], deps["sessions"],
                                      body.get("username", ""), body.get("password", ""), now,
                                      persona_provider=deps.get("persona_provider"))
            if result.outcome == "applied" and body.get("username", "") in _operator_users(deps):
                operator = deps["sessions"].sessions[result.body["token"]]
                operator.role = "operator"
                operator.ttl_s = _operator_session_seconds(deps)
            self._record_attempt("login", now, ok=result.outcome == "applied")
            if result.outcome == "applied":
                role = deps["sessions"].sessions[result.body["token"]].role
                return self._redirect("/operations" if role == "operator" else "/settings",
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
            if result.outcome == "refused" and result.status == 401:
                return self._redirect("/login")
            notice = result.body.get("detail") or result.body.get("reason", "")
            settings = deps["source"].current_settings() if deps.get("source") else {}
            return self._html_response(result.status, _with_nav(sw.render_settings_page(settings, notice), "/settings"))

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
            try:
                authorization = store.confirm(session, challenge_id, body.get("typed", ""), body.get("secret", ""))
            except hitl.ConfirmationError as exc:
                if exc.reason in ("phrase", "credential"):
                    self._record_attempt("confirm", now, ok=False)
                return self._json(403, {"outcome": "refused", "detail": f"refused: {exc}", "reason": exc.reason})
            self._record_attempt("confirm", now, ok=True)
            action_id, params, _serial = request
            return self._start_drive_job(deps, action_id, params, authorization, store)

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
    server = http.server.HTTPServer((host, port), UnifiedHandler)
    server.deps = deps  # type: ignore[attr-defined]
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
    settings_server = sw.build_real_server(bind_host="127.0.0.1", bind_port=0,
                                            data_path=data_path or Path("/var/lib/baseline/settings-web/store.json"),
                                            runner=runner)
    deps = dict(settings_server.deps)
    deps["vg_name"] = drive_installer.DEFAULT_VG_NAME
    deps["config_path"] = cpw.DEFAULT_CONFIG_PATH
    deps["network_interface"] = "eno1"
    deps["pds_runner"] = pds.Runner()
    # Operations: only the web service holds the signing key (root-only file); nothing else can ask for one to run.
    state = Path(state_dir or DEFAULT_STATE_DIR)
    audit_path = state / "audit" / "web-actions.jsonl"
    audit = hitl.AuditFile(audit_path)
    gate = wg.WebGate(wg.load_or_create_key(state / "web-signing.key"), audit=audit)
    wg.configure(gate)
    deps["web_gate"] = gate
    deps["audit"] = audit
    deps["operator_accounts"] = operator_accounts.OperatorAccounts(state / "operators.json")
    deps["scheduler"] = ops.Scheduler(
        gate, ops.ScheduleStore(state / "schedules.json"),
        lambda op, params, origin: _start_operation_job(deps, op, params, origin))
    import settings_store
    deps["operator_users"] = lambda: settings_store.get_setting("access", "operator_users")
    deps["operator_session_hours"] = lambda: settings_store.get_setting("access", "operator_session_hours")
    deps["hitl_audit_path"] = audit_path
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


def main() -> int:
    import os
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8100
    data_path = sw.resolve_data_path(os.environ)
    server = build_real_server(port=port, data_path=data_path)
    print(f"Baseline web app on http://0.0.0.0:{port}/  (login: this machine's account password)")
    print(f"Data store: {data_path}")
    server.deps["scheduler"].start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
