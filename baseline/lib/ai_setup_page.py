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
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>{_STYLE}</head><body>"
            f"<h1>{html.escape(title)}</h1>{body}</body></html>").encode()


def render_overview(provider_states, vault_status, notices):
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
    return _page("AI providers", f"{notes}<table><thead><tr><th>Provider</th><th>State</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table>"
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
