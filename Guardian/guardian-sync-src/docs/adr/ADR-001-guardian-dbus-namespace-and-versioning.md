# ADR-001: Guardian D-Bus namespace and interface versioning

- Status: Accepted — permanent namespace selected (supersedes the G0 development-namespace decision recorded below)
- Date: 2026-08-30
- Governing gate: G0 — Public Contracts

## Context

Guardian Plane needs a stable well-known D-Bus name, interface namespace, and object-path convention before a public release. Reverse-domain names imply ownership, so the namespace cannot be chosen for aesthetics.

When G0 mechanics were first implemented, the repository contained no domain, organization URL, remote, or other evidence establishing legitimate ownership of a permanent namespace. G0 still needed a real, introspectable interface so its mechanics could be tested without fabricating ownership. That produced the temporary development decision preserved in this ADR under "Historical development decision".

The owner has since selected the permanent namespace. This ADR now records both decisions: the temporary one that G0 was originally built under, and the permanent one that governs the current contract.

## Public project identity

```text
Project display name:  Guardian Plane
Repository slug:       guardian-plane
Description:           A local-first system control and recovery plane for Ubuntu Linux.
```

Ubuntu is named as the target platform, not as part of Guardian Plane's owned brand. The public identity deliberately does not incorporate "Ubuntu", which would raise Canonical trademark considerations that this project has not taken on. The local development directory is named `Guardian`; that path is a machine-local artifact and is not the public identity.

## Decision

The permanent public D-Bus identity is:

```text
Well-known bus name:  io.github.cliffthelin.Guardian1
Guardian interface:   io.github.cliffthelin.Guardian1
Root object path:     /io/github/cliffthelin/Guardian1
Error namespace:      io.github.cliffthelin.Guardian1.Error.*
```

Public interface names carry a numeric major suffix from their first version. Compatible additive changes may remain in `Guardian1`; incompatible signature, removal, meaning, error-semantic, or authorization-semantic changes require a new major. Object paths mirror the namespace as slash-separated components and end in the interface-major root. Future Guardian interfaces follow the same rule, for example `io.github.cliffthelin.Guardian.Capabilities1` at `/io/github/cliffthelin/Guardian1/Capabilities`.

The harmless read-only G0 methods report contract version and service state. They do not imply system-management capability.

## Ownership basis

The namespace derives from `github.com/cliffthelin`, a GitHub account the repository owner states they control. `io.github.<owner>` is the established reverse-domain convention for projects whose durable identity is a GitHub namespace rather than a registered DNS domain: GitHub controls `github.io`, and the account holder controls their subdomain of it.

Verification status is recorded honestly: this workstation carries no GitHub credentials, no `gh` installation, no SSH keys, and this repository has no remote. `git config user.name` is `Codex`/`codex@local`, a local agent identity, not an ownership fact. The ownership basis for this decision is therefore the owner's explicit attestation, not a machine-verified credential. Before the repository is published, the owner should confirm that `github.com/cliffthelin` is the account that will host `guardian-plane`; if a different account or organization ends up hosting it, this ADR must be superseded and the namespace migrated before any release, not afterwards.

`cliffthelin` is a valid D-Bus name element: it matches `[A-Za-z_][A-Za-z0-9_]*`, contains no hyphen, and does not begin with a digit, so it needs no mangling. This matters because many GitHub logins contain hyphens, which are illegal in D-Bus name components and would have forced an explicit, documented transformation.

The namespace is deliberately independent of the local Linux username, the hostname, the repository description, and the project display name. Renaming the project, rewriting its description, or restructuring its crates does not disturb it.

## Historical development decision

Preserved for the record; superseded, not deleted.

Until the owner selected a legitimate permanent namespace, G0 used this explicitly non-production namespace:

```text
Interface:   org.guardianproject.Development.Guardian1
Object path: /org/guardianproject/Development/Guardian1
```

`Development` was mandatory in every temporary public name and path. `org.guardianproject.Development` was a conspicuous development label, never an assertion that this repository owned `guardianproject.org`. That convention existed specifically so a temporary test namespace could not be mistaken for a production ownership claim. Commits `1ab7a47` through `3de9f1e` were authored under it, and the G0 evidence reports from that period correctly state it as the namespace in force at the time.

## Alternatives considered

- **Inventing a reverse-DNS domain** (`guardianproject.org`, `guardianplane.org`) — rejected. The project owns neither, and a reverse-DNS name is an ownership claim.
- **Keeping `org.guardianproject.Development` permanently** — rejected. It embeds "Development" in a production contract and still implies a domain the project does not own.
- **A namespace derived from the local username or hostname** — rejected. Machine-local identity is not durable public identity and does not survive moving the project to another machine or contributor.
- **An unqualified name** (`Guardian1`) — rejected. It violates D-Bus well-known-name convention and collides trivially on a shared system bus.
- **Waiting for a registered DNS domain** — rejected for now. It would block G0 indefinitely on a purchase decision, and `io.github.<owner>` is a legitimate, widely used durable basis. If the project later acquires a domain, migrating is a deliberate superseding decision, not an accident.

## Evidence and tests

- `P0-DBUS-001` recursively introspects the live registered object on a private bus and compares the complete structural contract, including annotations, against the committed `dbus/interfaces/io.github.cliffthelin.Guardian1.xml`.
- `P0-DBUS-002` enforces the explicit terminal interface-major suffix on every Guardian-owned interface.
- `P0-DBUS-003` requires the reachable Guardian method surface to equal exactly the two approved fully-qualified root methods, which is what excludes a generic execution surface.
- `P0-DBUS-004` pins all 17 public typed error names and proves one over a real private D-Bus connection.
- `P0-DBUS-005` verifies structured `org.freedesktop.DBus.Error.UnknownMethod` failure and continued service operation.
- `docs/evidence/g0/live-introspection.xml` is the capture under the permanent namespace; `docs/evidence/g0/live-introspection.development-namespace-3de9f1e.xml` preserves the development-namespace capture.

These tests are rooted in `docs/guardian/20_Control_Plane/D-Bus_API_Contract.md` and the local Ubuntu/zbus source snapshots.

## Consequences

The G0 naming decision gate in TDD contract §7.1 — "the reverse-domain / permanent bus namespace MUST be selected before G0 passes" — is now satisfied, so the gate verdict is no longer `MECHANICALLY GREEN / NAMESPACE DECISION PENDING`.

Changing the namespace again is intentionally expensive and is treated as a migration, not a cosmetic rename. It would change well-known names, interface identities, object paths, all 17 typed error names, generated client bindings, introspection fixtures, D-Bus bus policy, systemd/D-Bus service activation files, polkit action identifiers, packaging, and any installed client's expectations. Because the current public surface is two read-only methods and there are no shipped clients, this is the cheapest possible moment to have made the change.

## Rollback and migration

The development namespace carried no compatibility promise, so replacing it required no deprecation period. That grace period is now over: once `io.github.cliffthelin.Guardian1` ships in a package, a later rename requires a versioned compatibility/migration plan — running both interface names for a transition window — rather than silent replacement.

If the owner discovers before release that `github.com/cliffthelin` is not the hosting account, the correct response is a superseding ADR plus an atomic namespace migration and a full G0 rerun, following the same procedure used here.
