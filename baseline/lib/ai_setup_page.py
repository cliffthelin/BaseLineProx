"""Rendering for the browser-guided AI provider setup (`/ai-setup`). See provider_setup.py and vault.py."""
from __future__ import annotations

import html

import providers

KEY_PAGES = {
    "OPENAI_API_KEY": ("OpenAI", "https://platform.openai.com/api-keys"),
    "GEMINI_API_KEY": ("Google Gemini", "https://aistudio.google.com/app/apikey"),
    "OPENROUTER_API_KEY": ("OpenRouter", "https://openrouter.ai/keys"),
}
SCOPES = {"admin": "USER_ADMIN vault (this host's own credentials)", "personal": "USER_PERSONAL vault (yours)"}
CLAUDE_URL_PREFIX = "https://claude.com/"


def paste_target(name, scope):
    if name not in KEY_PAGES and name != "CLAUDE_CODE_OAUTH_TOKEN":
        raise ValueError("not a provider secret this page manages")
    if scope not in SCOPES:
        raise ValueError("unknown vault")
    return name, scope


_STYLE = ("<style>:root{color-scheme:dark}body{font-family:system-ui,sans-serif;background:#0d0e13;color:#e7e9f0;max-width:860px;"
          "margin:1.5rem auto;padding:0 1rem}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.5rem;"
          "border-bottom:1px solid #33364a}a{color:#9db4ec}input,select,button{font:inherit;padding:.4rem;color:#e7e9f0;background:#171923;"
          "border:1px solid #33364a;border-radius:5px}button{cursor:pointer;background:#2c4fb8}section{margin:1.6rem 0}</style>")


def _page(title, body):
    body = "<p><a href='/ai-setup/installer'>Installer AI setup and target access</a></p>" + body
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>{_STYLE}</head><body>"
            f"<h1>{html.escape(title)}</h1>{body}</body></html>").encode()


def render_overview(provider_states, vault_status, notices, harnesses=()):
    rows = "".join(f"<tr><td>{html.escape(p['name'])}</td><td>{html.escape(providers.display_status(p['state']))}</td>"
                   f"<td>{html.escape(p['detail'])}</td></tr>" for p in provider_states)
    held = "".join(f"<tr><td>{html.escape(s['name'])}</td><td>{s['length']} characters</td><td>{html.escape(s['fingerprint'])}</td></tr>"
                   for s in vault_status) or "<tr><td colspan='3'>nothing stored yet</td></tr>"
    paste = "".join(
        f"<section><h3>{html.escape(label)}</h3><p>Create a key at <a href='{url}' target='_blank' rel='noopener'>{html.escape(url)}</a>, "
        f"then paste it here.</p><form method='post' action=\"/ai-setup/paste\"><input type='hidden' name='name' value='{name}'>"
        f"<input name='value' type='password' autocomplete='off' placeholder='key' required> "
        f"<select name='scope'>{''.join(f'<option value={k}>{html.escape(v)}</option>' for k, v in SCOPES.items())}</select> "
        f"<button type='submit'>Save to vault</button></form></section>" for name, (label, url) in KEY_PAGES.items())
    notes = "".join(f"<p>{html.escape(n)}</p>" for n in notices)
    tools = "".join(f"<tr><td>{html.escape(h['name'])}</td><td>{'installed' if h['installed'] else 'NOT INSTALLED'}</td>"
                    f"<td>{html.escape(h['credential'])}</td></tr>" for h in harnesses)
    harness_table = (f"<section><h2>Harnesses</h2><table><thead><tr><th>Harness</th><th>Tool on this host</th><th>Credential</th></tr>"
                     f"</thead><tbody>{tools}</tbody></table></section>") if tools else ""
    return _page("AI providers", f"{notes}{harness_table}<table><thead><tr><th>Provider</th><th>State</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table>"
                 "<section><h2>Claude: sign in with your account</h2><p>You sign in on Anthropic's own site and grant access; "
                 "Baseline stores the resulting token in the vault.</p><form method='post' action=\"/ai-setup/claude/start\">"
                 "<button type='submit'>Connect Claude</button></form></section>"
                 f"<section><h2>Other providers</h2>{paste}</section>"
                 f"<section><h2>In the vault</h2><table><thead><tr><th>Name</th><th>Size</th><th>Fingerprint</th></tr></thead><tbody>{held}"
                 "</tbody></table></section>")


def render_claude(state):
    phase, message = state["phase"], html.escape(state.get("message") or "")
    refresh = "<meta http-equiv='refresh' content='3'>" if phase in ("starting", "finishing") else ""
    if phase == "waiting_for_code" and state.get("url"):
        url = html.escape(state["url"], quote=True)
        body = (f"<p>1. <a href=\"{url}\" target='_blank' rel='noopener'>Sign in to Claude and grant access</a> "
                "(opens Anthropic's own site).</p><p>2. Copy the code it shows and paste it here:</p>"
                "<form method='post' action=\"/ai-setup/claude/code\"><input name='code' autocomplete='off' required autofocus> "
                "<button type='submit'>Finish</button></form>"
                "<form method='post' action=\"/ai-setup/claude/cancel\"><button type='submit'>Cancel</button></form>")
    else:
        body = f"<p>{message}</p><p><a href='/ai-setup'>Back to AI providers</a></p>"
    return _page("Connect Claude", refresh + body)


def render_vault(states, notice="", secrets=(), places=()):
    """states: [{label, has_passphrase, unlocked, count}] for the admin and personal vaults."""
    rows = ""
    for st in states:
        state = "Not mounted" if not st.get("available", True) else "No passphrase (stored as plain files)" if not st["has_passphrase"] else ("Unlocked for this boot" if st["unlocked"] else "Locked")
        rows += f"<tr><td>{html.escape(st['label'])}</td><td>{html.escape(state)}</td><td>{st['count']}</td></tr>"
    any_unset = any(st.get("available", True) and not st["has_passphrase"] for st in states)
    any_sealed = any(st.get("available", True) and st["has_passphrase"] for st in states)
    forms = ""
    if any_unset:
        forms += ("<section><h2>Set a vault passphrase</h2><p>Seals every secret on the drive (AES-256, authenticated). The passphrase is "
                  "never stored; lose it and the sealed secrets cannot be recovered.</p>"
                  "<form method=\"post\" action=\"/vault/set\"><input name='passphrase' type='password' autocomplete='new-password' "
                  "placeholder='passphrase (12+ characters)' required> <input name='again' type='password' autocomplete='new-password' "
                  "placeholder='again' required> <button type='submit'>Seal the vault</button></form></section>")
    if any_sealed:
        forms += ("<section><h2>Unlock for this boot</h2><form method=\"post\" action=\"/vault/unlock\">"
                  "<input name='passphrase' type='password' autocomplete='current-password' required> "
                  "<button type='submit'>Unlock</button></form><form method=\"post\" action=\"/vault/lock\">"
                  "<button type='submit'>Lock now</button></form></section>")
    note = f"<p>{html.escape(notice)}</p>" if notice else ""
    held = "".join(
        f"<tr><td>{html.escape(item['name'])}</td><td>{html.escape(item['label'])}</td>"
        f"<td>{'sealed' if item.get('locked') else str(item.get('length')) + ' characters'}</td><td><code>{html.escape(item['fingerprint'])}</code></td>"
        f"<td><button type='button' data-act='show' data-scope='{html.escape(item['scope'], quote=True)}' data-name='{html.escape(item['name'], quote=True)}'>Show</button> "
        f"<button type='button' data-act='delete' data-scope='{html.escape(item['scope'], quote=True)}' data-name='{html.escape(item['name'], quote=True)}'>Delete</button> "
        f"<code class='shown'></code></td></tr>" for item in secrets) or "<tr><td colspan='5'>Nothing stored yet. Add a password, token or key below.</td></tr>"
    add = ("<section><h2>Add a secret</h2><form id='vault-add'><input name='name' placeholder='NAME_IN_CAPITALS' pattern='[A-Z][A-Z0-9_]{2,63}' required> "
           "<input name='value' type='password' autocomplete='off' placeholder='the password, token or key' required> "
           "<select name='scope'><option value='personal'>Mine (USER_PERSONAL)</option><option value='admin'>This computer's (USER_ADMIN)</option></select> "
           "<button type='submit'>Save</button></form></section>")
    names = sorted({item["name"] for item in secrets})
    cards = ""
    for place in places:
        boxes = "".join(f"<label><input type='checkbox' data-target='{html.escape(place['target'], quote=True)}' data-name='{html.escape(n, quote=True)}'"
                        f"{' checked' if n in place.get('granted', []) else ''}> {html.escape(n)}</label> " for n in names) or "<span>No secrets yet.</span>"
        cards += (f"<section><h3>{html.escape(place['label'])}</h3><div class='grants'>{boxes}</div>"
                  f"<button type='button' data-send='{html.escape(place['target'], quote=True)}'>Send the chosen secrets now</button> <span class='sent' role='status'></span></section>")
    use = ("<h2>Where each secret can be used</h2><p>Tick what a place may use, then send. The value goes into that machine's memory only "
           "(<code>/run/baseline-vault/NAME</code>, readable by its owner); it is never written to its disk and is gone when it stops. Web applications on this console use the vault directly.</p>"
           + (cards or "<p>No machines to send to yet.</p>"))
    script = """<script>
document.addEventListener('change',async e=>{const c=e.target.closest('input[data-target]');if(!c)return;
  const j=await call(c.checked?'/vault/grant':'/vault/revoke',{target:c.dataset.target,name:c.dataset.name});if(!j.ok){alert(j.message);c.checked=!c.checked;}});
document.addEventListener('click',async e=>{const b=e.target.closest('button[data-send]');if(!b)return;const out=b.parentElement.querySelector('.sent');out.textContent='Sending…';
  const j=await call('/vault/deliver',{target:b.dataset.send});out.textContent=j.message+(j.skipped&&Object.keys(j.skipped).length?' — '+Object.entries(j.skipped).map(([k,v])=>k+': '+v).join('; '):'');});
async function call(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return r.json();}
document.getElementById('vault-add').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.target);const j=await call('/vault/put',Object.fromEntries(f));
  if(!j.ok){alert(j.message);return;}location.href='/vault?notice='+encodeURIComponent(j.message);});
document.addEventListener('click',async e=>{const b=e.target.closest('button[data-act]');if(!b)return;const row=b.closest('tr');
  if(b.dataset.act==='delete'){if(!confirm('Delete '+b.dataset.name+'?'))return;const j=await call('/vault/delete',{scope:b.dataset.scope,name:b.dataset.name});
    if(!j.ok){alert(j.message);return;}location.reload();}
  else{const out=row.querySelector('.shown');if(out.textContent){out.textContent='';b.textContent='Show';return;}
    const j=await call('/vault/reveal',{scope:b.dataset.scope,name:b.dataset.name});if(!j.ok){alert(j.message);return;}
    out.textContent=j.value;b.textContent='Hide';setTimeout(()=>{out.textContent='';b.textContent='Show';},30000);}});
</script>"""
    return _page("Credential vault", f"{note}<table><thead><tr><th>Secret</th><th>Vault</th><th>Size</th><th>Fingerprint</th><th></th></tr></thead><tbody>{held}</tbody></table>"
                 f"{add}{use}<p><a href='/ai-setup/installer'>Installer AI profiles and guest access</a></p><h2>Protection</h2><table><thead><tr><th>Vault</th><th>State</th><th>Secrets</th></tr></thead><tbody>{rows}"
                 f"</tbody></table>{forms}<p><a href='/ai-setup'>AI providers</a></p>{script}")


def render_security(pending, notice=""):
    """pending: {userid: (secret, uri)} for enrolments that are waiting for their first code."""
    note = f"<p>{html.escape(notice)}</p>" if notice else ""
    waiting = "".join(
        f"<section><h2>{html.escape(u)}: confirm your authenticator</h2><p>Enter this key in your authenticator app "
        f"(or open the link on a phone with one): <code data-secret=\"{html.escape(sec, quote=True)}\">{html.escape(sec)}</code></p>"
        f"<p><a href=\"{html.escape(uri, quote=True)}\">{html.escape('Open in authenticator')}</a></p>"
        "<form method=\"post\" action=\"/security/tfa/confirm\">"
        f"<input type='hidden' name='userid' value='{html.escape(u, quote=True)}'>"
        "<input name='code' inputmode='numeric' autocomplete='one-time-code' maxlength='6' placeholder='6-digit code' required> "
        "<button type='submit'>Turn on two-factor</button></form></section>" for u, (sec, uri) in pending.items())
    return _page("Two-factor authentication", f"{note}{waiting}<section><h2>Set up two-factor for a Proxmox user</h2>"
                 "<form method=\"post\" action=\"/security/tfa/start\"><input name='userid' value='baseline@pam' required> "
                 "<button type='submit'>Start</button></form><p>Uses a time-based code (TOTP), the kind every authenticator app makes. "
                 "Baseline registers it with Proxmox only after your code checks out, so a mistyped key cannot lock you out.</p></section>")
