# DR216: Malformed Baseline configuration is unknown in inventory

**Status:** Accepted  
**Date:** 2026-10-09

## Context

The machine-inventory collector converted malformed JSON or a non-object JSON
configuration file into an empty key list. That result was indistinguishable
from a valid empty configuration.

## Decision

The collector now rejects malformed JSON and non-object roots. It records
`keys: null`, a diagnostic, and a collection note for parse failures. Failed
file reads likewise keep keys unknown and preserve the read reason. Valid JSON
objects with no keys still produce a confirmed empty list.

## Evidence and scope

The focused Baseline-configuration, inventory-manifest, and inventory-validator
suite passed 25 tests with the inventory `FakeRunner`. This verifies collector
and manifest behavior with synthetic file observations only; no host
configuration files were read.

## Remaining work

This closes one false-empty path in REAL-006. Other collectors still require
the same failure-versus-empty audit, and live inventory verification remains
open.
