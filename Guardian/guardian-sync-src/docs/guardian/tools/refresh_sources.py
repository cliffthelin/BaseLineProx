#!/usr/bin/env python3
"""
Refresh Guardian external source caches from 90_Sources/source_registry.json.

This tool intentionally DOES NOT overwrite Guardian-authored wiki interpretation
pages. It fetches canonical source URLs into 90_Sources/cache/ and records SHA-256
hashes so a maintainer can review changes before updating contracts or snapshots.
"""
from __future__ import annotations
import hashlib
import json
import pathlib
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "90_Sources" / "source_registry.json"
CACHE = ROOT / "90_Sources" / "cache"
HASHES = ROOT / "90_Sources" / "source_hashes.json"

CACHE.mkdir(parents=True, exist_ok=True)

registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
previous = {}
if HASHES.exists():
    previous = json.loads(HASHES.read_text(encoding="utf-8")).get("sources", {})

results = {}
for src in registry["sources"]:
    sid = src["id"]
    url = src["url"]
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "GuardianWikiSourceRefresh/1.0 (+local documentation cache)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            content_type = r.headers.get("Content-Type", "")
        sha = hashlib.sha256(body).hexdigest()
        ext = ".html" if "html" in content_type.lower() else ".bin"
        out = CACHE / f"{sid}{ext}"
        out.write_bytes(body)
        old_sha = previous.get(sid, {}).get("sha256")
        results[sid] = {
            "url": url,
            "sha256": sha,
            "previous_sha256": old_sha,
            "changed": old_sha is not None and old_sha != sha,
            "content_type": content_type,
            "cache_file": str(out.relative_to(ROOT)),
            "status": "ok",
        }
        print(f"{sid}: {'CHANGED' if results[sid]['changed'] else 'ok'}")
    except Exception as e:
        results[sid] = {
            "url": url,
            "status": "error",
            "error": str(e),
        }
        print(f"{sid}: ERROR {e}")

HASHES.write_text(json.dumps({
    "refreshed_at": datetime.now(timezone.utc).isoformat(),
    "sources": results,
}, indent=2) + "\n", encoding="utf-8")

print(f"\nReview: {HASHES.relative_to(ROOT)}")
