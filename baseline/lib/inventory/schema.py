"""Manifest schema assembly: fixed shape, stable key ordering (sorted
JSON keys, so two runs with identical inputs produce byte-identical
output), and an injectable clock so tests can assert that determinism
without depending on wall-clock time."""
import json

SCHEMA_VERSION = 2


def build_manifest(source, host_label, categories, config_files, redaction_report, clock):
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": clock(),
        "source": source,
        "host_label": host_label,
        "categories": categories,
        "config_files": config_files,
        "redaction_report": redaction_report,
    }


def to_json(manifest):
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
