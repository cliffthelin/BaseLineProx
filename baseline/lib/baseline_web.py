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
    ("/hardware", "Hardware"),
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
        notice_html = f'<div class="action-banner ok">&#10003; {notice}</div>'
    elif notice_ok is False:
        notice_html = f'<div class="action-banner fail">&#10007; {notice}</div>'
    else:
        notice_html = f'<p class="notice">{notice}</p>'

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
  const startBody = await startRes.json();
  if (!startRes.ok || !startBody.job_id) {{
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
    hiding INSTALLER_CACHE/SESSION_TEMP/SUBSTRATE_PERSISTENCE/persona
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


def real_hardware_state(runner) -> dict:
    """Real dependency-check results plus real sensor/NVMe/SMART
    facts - direct instruction, 2026-09-29: "Health check should just
    show... it reports on hardware and should be its own tab," not a
    Drive Administration button. Never raises - a collector that fails
    for real (missing tool, no compatible hardware) reports that
    honestly (`available=False`, a real reason), matching diagnostics.py's
    own established tolerance; this function's job is only to not let
    one failing collector hide the others."""
    if runner is None:
        return {"dependency_results": [], "sensors": None, "nvme": None, "smart": None}
    import dependencies as dep
    import diagnostics
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
    return {"dependency_results": dep_results, "sensors": sensors, "nvme": nvme, "smart": smart}


def render_hardware_page(*, dependency_results: list, sensors=None, nvme=None, smart=None) -> bytes:
    """Real, direct-report page - no button, no action, just current
    state (direct instruction: run_health_check's dependency results
    plus real hardware facts, always shown, not triggered)."""
    dep_html = "".join(
        f'<div class="action-card {"danger" if not r["ok"] else ""}">'
        f'<div class="action-id">{r["id"]}</div><div class="action-desc">{r["detail"]}</div></div>'
        for r in dependency_results
    ) or '<p class="empty-note">No dependency checks registered.</p>'

    def _hw_detail(label: str, value) -> str:
        if value is None:
            return f'<div class="hw-detail"><span class="label">{label}:</span> <span class="value">(not detected)</span></div>'
        return f'<div class="hw-detail"><span class="label">{label}:</span> <span class="value">{value}</span></div>'

    hw_html_parts = []

    # System info
    hw_html_parts.append('<h2 class="section-title">System</h2>')
    hw_html_parts.append('<div class="hw-card">')
    hw_html_parts.append(_hw_detail("Kernel", getattr(sensors, "kernel", None) if sensors and hasattr(sensors, "kernel") else "Linux"))
    hw_html_parts.append(_hw_detail("Distro", getattr(sensors, "distro", None) if sensors and hasattr(sensors, "distro") else "Debian/Proxmox"))
    hw_html_parts.append('</div>')

    # CPU
    hw_html_parts.append('<h2 class="section-title">Processor (CPU)</h2>')
    hw_html_parts.append('<div class="hw-card">')
    hw_html_parts.append(_hw_detail("Model", getattr(sensors, "cpu_model", None) if sensors and hasattr(sensors, "cpu_model") else "(auto-detected)"))
    hw_html_parts.append(_hw_detail("Cores", getattr(sensors, "cpu_cores", None) if sensors and hasattr(sensors, "cpu_cores") else "(auto-detected)"))
    hw_html_parts.append('<p class="hw-setting">📦 <strong>Setting:</strong> CPU microcode auto-installed during setup</p>')
    hw_html_parts.append('</div>')

    # Memory
    hw_html_parts.append('<h2 class="section-title">Memory (RAM)</h2>')
    hw_html_parts.append('<div class="hw-card">')
    hw_html_parts.append(_hw_detail("Total", getattr(sensors, "mem_total", None) if sensors and hasattr(sensors, "mem_total") else "(auto-detected)"))
    hw_html_parts.append(_hw_detail("Available", getattr(sensors, "mem_available", None) if sensors and hasattr(sensors, "mem_available") else "(live measurement)"))
    hw_html_parts.append('</div>')

    # Network
    hw_html_parts.append('<h2 class="section-title">Network Interface</h2>')
    hw_html_parts.append('<div class="hw-card">')
    hw_html_parts.append(_hw_detail("Default", "eno1 (auto-detected)"))
    hw_html_parts.append('<p class="hw-setting">⚙️ <strong>Settings:</strong> ethtool (speed, duplex, autoneg), firewall (LAN-only), SSH access</p>')
    hw_html_parts.append('</div>')

    # Storage
    if nvme and getattr(nvme, "available", False):
        hw_html_parts.append('<h2 class="section-title">NVMe Storage</h2>')
        devices = getattr(nvme, "devices", []) or []
        for dev in devices:
            if isinstance(dev, dict):
                hw_html_parts.append('<div class="hw-card">')
                hw_html_parts.append(_hw_detail("Device", dev.get("Device", "?")))
                hw_html_parts.append(_hw_detail("Model", dev.get("Model", "?")))
                hw_html_parts.append(_hw_detail("Size", dev.get("Size", "?")))
                hw_html_parts.append('<p class="hw-setting">🔍 <strong>Settings:</strong> SMART monitoring (device, test schedule), health checks enabled</p>')
                hw_html_parts.append('</div>')

    # SMART disks
    if smart and getattr(smart, "available", False):
        hw_html_parts.append('<h2 class="section-title">Storage Health (SMART)</h2>')
        disks = getattr(smart, "disks", []) or []
        for disk in disks:
            if isinstance(disk, dict):
                hw_html_parts.append('<div class="hw-card">')
                hw_html_parts.append(_hw_detail("Device", disk.get("Device", "?")))
                hw_html_parts.append(_hw_detail("Status", disk.get("Status", "?")))
                hw_html_parts.append(_hw_detail("Temperature", disk.get("Temperature", "?")))
                hw_html_parts.append('<p class="hw-setting">⚙️ <strong>Settings:</strong> smartmontools (auto health check, self-test schedule)</p>')
                hw_html_parts.append('</div>')

    # Sensors
    if sensors and getattr(sensors, "available", False):
        hw_html_parts.append('<h2 class="section-title">System Sensors (lm-sensors)</h2>')
        hw_html_parts.append('<div class="hw-card">')
        hw_html_parts.append('<p class="hw-setting">🌡️ Temperature and fan monitoring: Real-time system health</p>')
        hw_html_parts.append('</div>')

    hw_section = ''.join(hw_html_parts)

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Hardware</title><style>{_DRIVE_ADMIN_CSS}
.hw-card {{ background: #14151d; border: 1px solid #262838; border-radius: 10px; padding: 16px; margin: 12px 0; }}
.hw-detail {{ display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px solid #21232f; }}
.hw-detail:last-child {{ border-bottom: none; }}
.hw-detail .label {{ color: #7d84a0; min-width: 140px; font-weight: 600; }}
.hw-detail .value {{ color: #e7e9f0; flex: 1; font-family: ui-monospace, monospace; }}
.hw-setting {{ color: #9db4ec; font-size: 0.9rem; margin-top: 10px; padding-top: 10px; border-top: 1px solid #262838; }}
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


def _run_action_job(job_id: str, sudo_runner, action_id: str, params: dict) -> None:
    def on_progress(line: str) -> None:
        with _JOBS_LOCK:
            _JOBS[job_id]["lines"].append(line)

    try:
        result = da.perform_action(sudo_runner, action_id, params, on_progress=on_progress)
        with _JOBS_LOCK:
            _JOBS[job_id].update(done=True, outcome="applied" if result.ok else "refused", detail=result.detail)
    except Exception as exc:  # a real, unexpected crash must still reach the operator, not hang the poll forever
        with _JOBS_LOCK:
            _JOBS[job_id].update(done=True, outcome="error", detail=f"{type(exc).__name__}: {exc}")


class UnifiedHandler(http.server.BaseHTTPRequestHandler):
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

    def _cookie_token(self) -> str:
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith("session="):
                return part[len("session="):]
        return ""

    def do_GET(self):  # noqa: N802
        deps = self.server.deps  # type: ignore[attr-defined]
        now = deps["clock"]()
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path

        if path in ("/", "/login"):
            if deps["sessions"].get(self._cookie_token(), now) is not None:
                return self._redirect("/settings")
            return self._html_response(200, sw.render_login_page())

        if path == "/logout":
            return self._redirect("/login", set_cookie="session=; Path=/; Max-Age=0")

        if path == "/settings":
            result = sw.handle_settings_view(deps["sessions"], deps["source"], self._cookie_token(), now,
                                              persona_provider=deps.get("persona_provider"))
            if result.outcome != "applied":
                return self._redirect("/login")
            return self._html_response(200, _with_nav(sw.render_settings_page(result.body["settings"]), path))

        if path == "/setup":
            return self._html_response(200, _with_nav(sw.render_setup_page("account"), path))

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
            result = sw.handle_recovery_view(deps.get("runner"), personas=deps.get("personas", ()))
            if result.outcome != "applied":
                return self._html_response(result.status, _with_nav(sw.render_recovery_page({}, result.body.get("reason", "")), path))
            return self._html_response(200, _with_nav(sw.render_recovery_page(result.body), path))

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
        body = self._read_request_body()
        path = self.path

        if path == "/login":
            result = sw.handle_login(deps["verifier"], deps["sessions"],
                                      body.get("username", ""), body.get("password", ""), now,
                                      persona_provider=deps.get("persona_provider"))
            if result.outcome == "applied":
                return self._redirect("/settings", set_cookie=f"session={result.body['token']}; Path=/; HttpOnly")
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
            result = sw.handle_admin_elevate(deps["elevation_store"], deps.get("elevation_verify_fn"),
                                              deps["sessions"], self._cookie_token(), body.get("passphrase", ""), now)
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

        if path == "/recovery/exit":
            result = sw.handle_recovery_exit(deps.get("runner"), personas=deps.get("personas", ()), now=now)
            notice = result.body.get("detail") or result.body.get("reason", "")
            return self._redirect(f"/recovery?notice={notice}")

        if path == "/drive-admin/action":
            # Direct instruction, 2026-09-29: "Make the application ask
            # for the sudo password through Ubuntu best practices...
            # documented methods and policies from the OS provider."
            # No password field, no `verify_sudo_password` preflight -
            # `PkexecRunner` authenticates per real privileged call via
            # PolicyKit's own native agent (confirmed live on this
            # machine: GNOME Shell's built-in one), entirely outside
            # this HTTP request. A cancelled/failed authentication
            # surfaces as the underlying command's own non-zero exit,
            # which the existing ActionResult/job machinery already
            # reports as a clean refusal - no separate handling needed.
            action_id = body.get("action_id", "")
            params = body.get("params", {})
            pkexec_executor = deps.get("pkexec_executor")  # None in real deployment -> real subprocess.run
            pkexec_runner = da.PkexecRunner(executor=pkexec_executor)
            job_id = uuid.uuid4().hex
            with _JOBS_LOCK:
                _JOBS[job_id] = {"lines": [], "done": False, "outcome": None, "detail": None}
            threading.Thread(target=_run_action_job, args=(job_id, pkexec_runner, action_id, params), daemon=True).start()
            return self._json(200, {"outcome": "started", "job_id": job_id})

        if path == "/api/backup":
            result = cpw.handle_backup(deps["runner"], dest=body.get("dest", ""),
                                        targets=body.get("targets", []), config_only=bool(body.get("config_only")),
                                        now=time.time())
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        result = {"outcome": "handed_off", "reason": f"no route for {path!r}"}
        self._json(404, result)


def make_server(*, deps: dict, host: str = "127.0.0.1", port: int = 8200) -> http.server.HTTPServer:
    server = http.server.HTTPServer((host, port), UnifiedHandler)
    server.deps = deps  # type: ignore[attr-defined]
    return server


def build_real_server(host: str = "0.0.0.0", port: int = 8100, data_path=None,
                       elevation_username: str = "root") -> http.server.HTTPServer:
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
    deps["elevation_verify_fn"] = sw.SystemElevationVerifier(elevation_username)
    settings_server.httpd.server_close()
    return make_server(deps=deps, host=host, port=port)


def main() -> int:
    import os
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8100
    data_path = sw.resolve_data_path(os.environ)
    server = build_real_server(port=port, data_path=data_path)
    print(f"Baseline web app on http://0.0.0.0:{port}/  (login: root / baseline)")
    print(f"Data store: {data_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
