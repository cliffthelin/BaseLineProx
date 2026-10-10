# DR217: Registry read failure is not an empty result

**Status:** Accepted  
**Date:** 2026-10-09

## Context

`registry.list_entries(..., read_only=True)` returned an empty mapping whenever
SQLite raised `OperationalError`. A missing database is a valid empty registry,
but an existing database with a missing table, malformed contents, or an I/O
failure is unknown state. Returning `{}` could hide settings, enrollment,
dependencies, or other registry-backed state.

## Decision

The missing-database fast path remains empty and read-only. Once a database
exists, a SQLite query failure raises `RegistryReadError` with its path and
diagnostic; callers must display or propagate the error rather than treating it
as no entries.

## Evidence and scope

The registry and direct consumer suite passed 489 tests: registry, drive admin,
settings store, drive guard/enrollment, AppData, off-drive backup, and
dependencies. Tests use disposable SQLite files and synthetic runners; no
production registry database or physical drive was read or changed.

## Remaining work

This repairs one shared false-empty result. It does not validate host registry
mounts, contents, backup, or recovery against the real deployment.
