"""The hardware overview the TUI's Hardware tab shows (group, item, detail) with each row opening to every field it reported, for the console's Hardware page."""
from __future__ import annotations

import html


def overview_rows(collect, full_inventory) -> tuple:
    """(rows, error): `collect()` and `full_inventory(raw)` are the TUI's own calls (hardware.collect / hardware.full_inventory), passed in so this is checked without running inxi."""
    raw, err = collect()
    if err:
        return [], str(err)
    return full_inventory(raw), ""


def render_section(rows, error: str = "") -> str:
    e = html.escape
    if error:
        return f'<section class="hw-overview"><h2>Overview</h2><p role="alert">Hardware overview unavailable: {e(error)}</p></section>'
    body = "".join(
        f'<tr><td>{e(str(r["group"]))}</td><td><details><summary>{e(str(r["label"]))}</summary>'
        f'<pre>{e(chr(10).join(f"{k}: {v}" for k, v in (r.get("fields") or {}).items()) or "(no fields reported)")}</pre></details></td><td>{e(str(r["detail"]))}</td></tr>'
        for r in rows) or '<tr><td colspan="3">nothing reported</td></tr>'
    return ('<section class="hw-overview"><h2>Overview</h2><table><thead><tr><th>Group</th><th>Item (select for every field)</th><th>Detail</th></tr></thead>'
            f'<tbody>{body}</tbody></table></section>')
