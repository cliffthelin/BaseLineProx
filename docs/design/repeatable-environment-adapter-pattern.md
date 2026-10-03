# Repeatable OS and application adapter pattern

2026-10-02, DR132. Accepted implementation direction for queue76 and74.
This is an extension contract/checklist, not an implemented universal installer.

Baseline must implement repeatable software workflows; AI may help author an
adapter or invoke a workflow but is not required to perform its runtime steps.
A request for another OS should reuse this sequence and identify the changes
needed at the adapter boundary before doing any installation.

## Shared sequence and adapter responsibilities

| Phase | Shared behavior | OS/application-specific input |
|---|---|---|
| Discover | Inspect actual target and report supported capabilities before writes | OS/release, architecture, guest type, package tools, ABI/runtime prerequisites, privilege and available GUI/session services |
| Inspect | Explicit target and selected configuration; classify before export | Native settings locations/parser, installed version, dependency inventory; no automatic whole-profile scraping |
| Capture | Preview portable allowlisted settings; exclude content/secrets; version the artifact | Supported setting names/types, migration rules, distinction between portable and machine-bound values |
| Resolve and lock | Resolve once, preserve exact source identity and configuration digest; subsequent rebuild uses the lock | Publisher/source trust, version/architecture, immutable artifact identity, dependency and extension versions; source availability failures are explicit |
| Acquire | Verify bytes before use; report cache/source provenance | Artifact format and verification mechanism; selected vanilla cache or external source, without requiring the Baseline drive |
| Plan state | Separate build configuration, disposable generation, retained data and private identity | Native state locations, owners, mount/volume mapping, service databases, credentials, migration compatibility and sharing requirements |
| Install candidate | Build into a new target; record allocations/partial failures | Package manager, image/container/native archive installer, native config renderer and prerequisite installation |
| Verify | Check actual source/version and effective configuration; readiness requires observed behavior | Application API/launch probe or OS boot/service probe, appropriate to VM/container/GUI/headless capabilities |
| Promote or recover | Use durable jobs and identity checks; preserve old generation until candidate passes | Stop/quiesce, attach retained state, data migration, compatible rollback and interrupted-operation recovery |
| Rebuild or restore | Reuse locked recipe and declared durable-state manifest; verify after reattachment | Base reacquisition, target identity mapping, native mounts/permissions and missing-source/data recovery |

These are responsibility boundaries, not new Python APIs or an instruction to
rewrite working helpers into a generic framework. Extract shared code when a
second real adapter demonstrates the same behavior. Keep publisher validation,
package semantics and native rendering in adapters. Do not dynamically load code
or execute shell commands from an imported recipe. An adapter is reviewed source;
a portable recipe is validated data.

## New adapter implementation checklist

1. Record the exact target OS/release/architecture and execution medium. Check
   existing helpers and evidence before adding an adapter. Guest support is
   distinct from backend support: a Proxmox-to-Harvester adapter is a separate
   change from supporting another guest OS.
2. Publish an explicit capability table: capture, source lock, acquisition,
   install, configure, launch, retained-state reset/rebuild, backup and restore.
   Each capability is unsupported, implemented but unverified, or verified with
   a named evidence environment. Support for one does not imply another.
3. Define native configuration mappings and writable-state inventory. Shared
   settings need semantic mappings; do not copy Linux paths onto another OS.
   Identify credentials/content/machine-bound values and exclude them from
   shareable builds. Standard full-disk VMs and containers without overlays remain
   valid; never silently convert them into disposable-root workloads.
4. Write and confirm failing behavioral tests before implementation. Test the
   actual boundary: unsupported targets, mismatched source, existing destination,
   invalid config, absent retained storage, partial failure and successful apply.
   Use synthetic data and a disposable target for initial integration.
5. Implement the smallest supported native path, with explicit prerequisites
   and errors. Verify a fresh installation and effective settings, then repeated
   locked installation on another fresh target. Existing destinations may safely
   refuse; repeatability does not require overwriting an existing profile.
6. Before claiming rebuild continuity, prove all declared durable data survives
   reset/rebuild and inspect excluded writable paths. Before claiming isolation,
   demonstrate denied cross-app access and explicit permitted sharing. Before
   replacement restore claims, test with original storage unavailable.
7. Update INSTALL, queue, handoff, capability status and an append-only decision
   record with exact verification scope. Publish evidence without credentials or
   user content. Keep unit/fake, development-host, disposable guest and physical
   deployment evidence separate.

## Current adapters and limits

| Component | Actual reusable starting point | Remaining boundary |
|---|---|---|
| environment_recipes.py | Strict configuration-only document parsing, validation, export and stack digest | Current allowlist is Ubuntu24.04 amd64 and Chromium; VS Code envelope is not yet integrated |
| vscode_capture.py | Approved portable settings preview and fresh native profile staging | Five settings only; other platforms/renderers, extensions and private-state migration unverified |
| vscode_build.py | Publisher Linux-x64 source/settings lock, verified download and fresh archive materialization | Not a distro package manager; no automatic guest/ABI prerequisites, managed job, cross-OS support or retained-state/isolation proof |
| Existing workload jobs / Ubuntu environment | Durable orchestration and scoped Ubuntu rebuild evidence | Generic application reconciliation and complete writable-state coverage remain open |

DR131 proved one actual fresh Linux archive launch, not two-target locked replay,
managed guest installation, another OS or total-device-loss recovery. Those tests
remain part of queue76. No capability is promoted by this document alone.

## When another OS throws a curveball

Examples include an immutable package model, no supported application binary,
a different configuration schema, no GUI in the container, missing sandbox
prerequisites or incompatible retained-data format. Report the observed mismatch
and the affected capability. Add a versioned adapter/migration and verification
when feasible; otherwise stop that capability with an explicit unsupported result.
Do not substitute a catalog entry, successful file copy or unit test for readiness.
