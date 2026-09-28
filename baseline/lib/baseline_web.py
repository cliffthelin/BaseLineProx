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
import time
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
.drive-card .drive-name { font-weight: 700; font-size: .96rem; margin-bottom: 2px; padding-right: 20px; }
.drive-card .drive-path { font-family: ui-monospace, "SF Mono", Menlo, monospace; color: #7d84a0; font-size: .82rem; margin-bottom: 10px; }
.drive-card .detail-row { display: flex; justify-content: space-between; font-size: .82rem; padding: 3px 0; border-top: 1px solid #21232f; margin-top: 8px; }
.drive-card .detail-row span:first-child { color: #7d84a0; }
.drive-card .detail-row span:last-child { font-family: ui-monospace, monospace; }
.volume-table { width: 100%; border-collapse: collapse; background: #14151d; border: 1px solid #262838; border-radius: 10px; overflow: hidden; }
.volume-table th { text-align: left; font-size: .72rem; text-transform: uppercase; letter-spacing: .06em; color: #7d84a0; padding: 9px 14px; background: #1a1c27; }
.volume-table td { padding: 9px 14px; font-size: .87rem; border-top: 1px solid #21232f; }
.volume-table td.mono { font-family: ui-monospace, monospace; color: #b9bdd4; }
.empty-note { color: #7d84a0; font-size: .87rem; padding: 10px 2px; }
.action-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
.action-card { background: #14151d; border: 1px solid #262838; border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
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
#driveAdminModal .hint { margin-top: 10px; }
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
        drive_cards = "".join(f"""
<label class="drive-card {'selected' if d['path'] == default_path else ''} {'acted-on-ok' if d['path'] == acted_on_path and notice_ok is True else ''} {'acted-on-fail' if d['path'] == acted_on_path and notice_ok is False else ''}">
  <input type="radio" name="targetDrive" value="{d['path']}" {"checked" if d['path'] == default_path else ""}>
  <span class="drive-type-pill">{d.get('drive_type', 'Other')}</span>
  {'<span class="acted-on-pill">last action</span>' if d['path'] == acted_on_path and notice_ok is not None else ''}
  <div class="drive-name">{d.get('model', 'Unknown model')}</div>
  <div class="drive-path">{d['path']}</div>
  <div class="detail-row"><span>Size</span><span>{d.get('size', '—')}</span></div>
  <div class="detail-row"><span>Partitions</span><span>{d.get('partition_count') if d.get('partition_count') is not None else '—'}</span></div>
  <div class="detail-row"><span>Data</span><span>{d.get('usage_text', 'unknown')}</span></div>
</label>""" for d in drives)
    else:
        drive_cards = '<p class="empty-note">No real candidate drives found (or the enumeration failed) - nothing selectable right now.</p>'

    if volumes:
        volume_rows = "".join(
            f"""<tr><td><input type="checkbox" class="volume-select" value="{v['label']}"></td>"""
            f"<td>{v['label']}</td><td class='mono'>{v['mountpoint']}</td><td class='mono'>{v.get('used', '-')}</td></tr>"
            for v in volumes
        )
        volumes_html = f"""<table class="volume-table">
<tr><th>Select</th><th>Volume</th><th>Mountpoint</th><th>Used</th></tr>{volume_rows}</table>"""
    else:
        volumes_html = '<p class="empty-note">No volumes currently mounted and reporting usage.</p>'

    action_cards = "".join(f"""
<div class="action-card {'danger' if 'PERMANENTLY ERASE' in a['description'] else ''}">
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
<div class="drive-grid">{drive_cards}</div>

<h2 class="section-title">Mounted volumes</h2>
<p class="subtitle">Select one or more volumes here, then use the Update action below to choose which types of update to apply to the selection.</p>
{volumes_html}

<h2 class="section-title">Actions</h2>
<div class="action-grid">{action_cards}</div>

<div id="driveAdminModal">
  <div class="box">
    <h3>Confirm this change</h3>
    <p id="driveAdminModalDescription"></p>
    <div id="driveAdminModalParams"></div>
    <label>Your system password
      <input id="driveAdminModalPassword" type="password" autocomplete="current-password">
    </label>
    <div class="modal-actions">
      <button type="button" id="driveAdminModalConfirm">Authorize and run</button>
      <button type="button" id="driveAdminModalCancel">Cancel</button>
    </div>
    <p class="hint">Runs immediately on confirm - real code executed by this already-running service, not a command handed back to you to run yourself.</p>
  </div>
</div>

<script id="driveAdminDriveData" type="application/json">{json.dumps(drives)}</script>
<script id="driveAdminActionData" type="application/json">{json.dumps({a["action_id"]: bool(a.get("requires_device")) for a in actions})}</script>
<script>
const driveList = JSON.parse(document.getElementById("driveAdminDriveData").textContent);
const requiresDeviceById = JSON.parse(document.getElementById("driveAdminActionData").textContent);

document.querySelectorAll('input[name="targetDrive"]').forEach(radio => {{
  radio.addEventListener("change", () => {{
    document.querySelectorAll(".drive-card").forEach(card => card.classList.remove("selected"));
    radio.closest(".drive-card").classList.add("selected");
  }});
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

function updateSelectedParamsHtml() {{
  const selected = selectedVolumeLabels();
  const selectedText = selected.length ? selected.join(", ") : "(none selected above)";
  return `<p>Selected: ${{selectedText}}</p>
    <label><input type="checkbox" id="paramTypeVolumeMode"> Apply volume mount mode</label>
    <label><input type="checkbox" id="paramTypeSwitchPersona"> Switch active persona</label>
    <label>Persona to switch to (only used if "Switch active persona" is checked)
      <input id="paramToPersona" value="personal"></label>`;
}}

let pendingActionId = null;
document.querySelectorAll(".drive-admin-action").forEach(btn => {{
  btn.addEventListener("click", () => {{
    pendingActionId = btn.dataset.actionId;
    document.getElementById("driveAdminModalDescription").textContent = btn.dataset.description;
    document.getElementById("driveAdminModalParams").innerHTML =
      requiresDeviceById[pendingActionId]
        ? deviceSelectHtml(currentlySelectedDrivePath())
        : pendingActionId === "update_selected"
        ? updateSelectedParamsHtml()
        : "";
    document.getElementById("driveAdminModal").classList.add("open");
    document.getElementById("driveAdminModalPassword").focus();
  }});
}});
document.getElementById("driveAdminModalCancel").addEventListener("click", () => {{
  document.getElementById("driveAdminModal").classList.remove("open");
  document.getElementById("driveAdminModalPassword").value = "";
}});
document.getElementById("driveAdminModalConfirm").addEventListener("click", async () => {{
  const password = document.getElementById("driveAdminModalPassword").value;
  const params = {{}};
  const devicePath = document.getElementById("paramDevicePath");
  const toPersona = document.getElementById("paramToPersona");
  const typeVolumeMode = document.getElementById("paramTypeVolumeMode");
  const typeSwitchPersona = document.getElementById("paramTypeSwitchPersona");
  if (devicePath) params.device_path = devicePath.value;
  if (pendingActionId === "update_selected") {{
    params.selected = selectedVolumeLabels();
    params.update_types = [
      ...(typeVolumeMode && typeVolumeMode.checked ? ["apply_volume_mode"] : []),
      ...(typeSwitchPersona && typeSwitchPersona.checked ? ["switch_persona"] : []),
    ];
    if (toPersona) params.to_persona = toPersona.value;
  }}
  document.getElementById("driveAdminModalPassword").value = "";
  const res = await fetch("/drive-admin/action", {{
    method: "POST", headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{action_id: pendingActionId, params, password}}),
  }});
  const body = await res.json();
  document.getElementById("driveAdminModal").classList.remove("open");
  const ok = res.ok && body.outcome === "applied" ? "1" : "0";
  const text = body.detail || body.error || body.reason || "done";
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
    try:
        usage = drive_installer.collect_volume_usage(runner)
    except Exception:
        return []
    return [{"label": u.label, "mountpoint": u.mountpoint, "used": getattr(u, "used_bytes", "-")} for u in usage]


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

        if path.startswith("/admin"):
            result = sw.handle_admin_view(deps["sessions"], deps.get("runner"), self._cookie_token(), now)
            if result.outcome == "refused" and result.status == 401:
                return self._redirect("/login")
            if result.outcome != "applied":
                return self._html_response(result.status, _with_nav(sw.render_admin_page({}, result.body.get("reason", "")), path))
            notice = qs.get("notice", [""])[0]
            elevated = deps["elevation_store"].is_elevated(deps.get("runner"), now) if deps.get("runner") else False
            return self._html_response(200, _with_nav(sw.render_admin_page(result.body["settings"], notice, elevated=elevated), path))

        if path.startswith("/recovery"):
            result = sw.handle_recovery_view(deps.get("runner"), personas=deps.get("personas", ()))
            if result.outcome != "applied":
                return self._html_response(result.status, _with_nav(sw.render_recovery_page({}, result.body.get("reason", "")), path))
            return self._html_response(200, _with_nav(sw.render_recovery_page(result.body), path))

        if path.startswith("/drive-admin/actions"):
            return self._json(200, {"actions": da.describe_actions()})

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
            action_id = body.get("action_id", "")
            params = body.get("params", {})
            password = body.get("password", "")
            sudo_executor = deps.get("sudo_executor")  # None in real deployment -> real subprocess.run
            if not da.verify_sudo_password(password, executor=sudo_executor):
                return self._json(401, {"error": "invalid password - action refused"})
            sudo_runner = da.SudoRunner(password, executor=sudo_executor)
            result = da.perform_action(sudo_runner, action_id, params)
            return self._json(200 if result.ok else 422, {"outcome": "applied" if result.ok else "refused", "detail": result.detail})

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
    (decision record 84) - it authenticates via a real `sudo -S`
    directly (`drive_admin.verify_sudo_password`/`SudoRunner`), using
    the password the operator just typed into the modal, so this app
    never needs to already be running as root - real self-elevation,
    not a pre-elevated process. `deps["sudo_executor"]` is left unset
    here (`None`), which both of those real production calls
    already treat as "use the real `subprocess.run`" - only tests
    inject a fake one.

    `elevation_username` (default `"root"`) and
    `settings_web.SystemElevationVerifier` remain real and in use for
    the separate Admin tab's own settings-editing gate
    (`handle_admin_edit`, decision record 80) - a different, lighter
    check for a different, lighter class of change than Drive
    Administration's real destructive actions."""
    from pathlib import Path
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
