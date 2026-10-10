# DR240 — inxi schema rejects missing core observations

**Status:** Implemented and contract tested; no live hardware inventory run  
**Date:** 2026-10-09

## Context

The inxi collector accepted any syntactically valid JSON. An empty object,
empty list, malformed section, or inventory without useful System and CPU
observations could therefore be normalized into a complete-looking schema
full of null values.

## Decision

Require a nonempty list of section objects, with valid, nonempty System and
CPU sections. The collector reports invalid structures as an inventory error;
direct normalization raises `HardwareInventoryError`. Optional sections such
as Network and Drives may be absent because machines can legitimately lack
those observations.

## Evidence and scope

Seven pure contract tests passed, including malformed top-level input, absent
required sections, empty required sections, and valid data with optional
sections absent. Tests were written first and failed before implementation.
No FakeRunner/FakeProc or live inxi command was used.

## Remaining work

These checks validate the inxi data shape, not the accuracy or completeness of
a real host's output. Live inventory collection remains unverified.
