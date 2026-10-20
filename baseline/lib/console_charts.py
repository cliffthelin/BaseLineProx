"""Small inline charts for the console pages, drawn the same way for every page (no script, no library)."""
from __future__ import annotations

import html


def sparkline_svg(values, *, label: str, unit: str = "", width: int = 220, height: int = 36) -> str:
    """A trend line of `values` with a dot on the latest one and its range in words. Empty input says so instead of drawing nothing."""
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    if not nums:
        return f'<p class="chart-empty">{html.escape(label)}: no history yet</p>'
    lo, hi = min(nums), max(nums)
    span = (hi - lo) or 1.0
    pad = 4
    step = (width - 2 * pad) / max(len(nums) - 1, 1)
    points = [(pad + i * step, height - pad - (v - lo) / span * (height - 2 * pad)) for i, v in enumerate(nums)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    x, y = points[-1]
    words = f"{label}: now {nums[-1]:g}{unit}, lowest {lo:g}{unit}, highest {hi:g}{unit} over {len(nums)} readings"
    return (f'<figure class="chart"><svg role="img" aria-label="{html.escape(words)}" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
            f'<polyline points="{line}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="currentColor"/></svg><figcaption>{html.escape(words)}</figcaption></figure>')
