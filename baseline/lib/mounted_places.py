"""Mounted partitions a person can choose from (no typed locations). Real block-device mounts under the connected-drive places."""
from __future__ import annotations

import json
import re

PLACES = ("/mnt/", "/media/", "/run/media/")
_SAFE = re.compile(r"^/[A-Za-z0-9._/-]+$")


def parse(findmnt_json: str) -> list:
    try:
        tree = json.loads(findmnt_json)
        roots = tree["filesystems"]
        if not isinstance(roots, list):
            return []
    except (ValueError, KeyError, TypeError):
        return []
    out = []

    def walk(nodes):
        for node in nodes:
            target, source = node.get("target", ""), node.get("source", "")
            if (isinstance(target, str) and isinstance(source, str) and re.fullmatch(r"/dev/(sd|nvme|vd|mmcblk|mapper/)[A-Za-z0-9._/-]*[0-9a-z]", source)
                    and target.startswith(PLACES) and _SAFE.fullmatch(target) and ".." not in target):
                out.append({"target": target, "source": source, "fstype": node.get("fstype", "")})
            walk(node.get("children") or [])
    walk(roots)
    return out


def choose(value, offered) -> str:
    if value not in {m["target"] for m in offered}:
        raise ValueError("choose one of the mounted partitions listed")
    return value
