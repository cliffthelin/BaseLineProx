"""Layer manifest digests and TPM PCR extension (hardened-appliance-prd.md, R4.2).

A layer manifest is the canonical JSON of a layer's registry entries, never
a raw SQLite file (WAL and page reuse make that hash unstable). The digest is
domain-separated by layer name. `extend_pcr` only shells out through a
caller-supplied runner, so nothing here touches a TPM on its own.
"""
from __future__ import annotations

import hashlib
import json
import re

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PCR_MIN, _PCR_MAX = 0, 23
_DOMAIN = "baseline-layer-manifest-v1"


class PcrExtendError(RuntimeError):
    pass


def canonical_json(entries) -> bytes:
    return json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def layer_digest(layer_name: str, entries) -> str:
    h = hashlib.sha256()
    h.update(_DOMAIN.encode("ascii") + b"\0" + layer_name.encode("utf-8") + b"\0")
    h.update(canonical_json(entries))
    return h.hexdigest()


def expected_pcr_after_extend(old_pcr_hex: str, digest_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(old_pcr_hex) + bytes.fromhex(digest_hex)).hexdigest()


def extend_pcr(runner, pcr_index: int, digest_hex: str) -> None:
    if not _PCR_MIN <= pcr_index <= _PCR_MAX:
        raise ValueError(f"PCR index out of range: {pcr_index}")
    if not _DIGEST_RE.match(digest_hex):
        raise ValueError("digest must be 64 lowercase hex characters")
    rc, _out, err = runner.run(["tpm2_pcrextend", f"{pcr_index}:sha256={digest_hex}"])
    if rc != 0:
        raise PcrExtendError(f"tpm2_pcrextend failed (rc={rc}): {err.strip()}")
