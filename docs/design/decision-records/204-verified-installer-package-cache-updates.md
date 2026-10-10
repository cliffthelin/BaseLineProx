# DR204: Refresh cached Debian packages through the host APT trust policy

Date: 2026-10-09  
Status: accepted

## Context

Drive Administration exposed `Update selected`, but `check_cache_updates()` always raised and
`update_selected()` returned a hard-coded “not implemented” failure. The volume selector also
offered user and operating-system volumes even though updateable installer archives live only in
`INSTALLER_CACHE`.

## Decision

The action now updates cached Debian package and firmware `.deb` artifacts in
`/mnt/INSTALLER_CACHE/packages` only. It requires the label and UUID of the mounted
`INSTALLER_CACHE` filesystem, a canonical `packages` directory on that same filesystem, and an
APT metadata refresh with insecure repositories and unauthenticated packages disabled. Cached
package identity, version, and architecture are read from each archive; current APT candidates are
compared using `dpkg --compare-versions`. New archives are downloaded with `--download-only` into
the cache and re-read with `dpkg-deb` before success is reported. No package is installed on the
running host. The volume selector disables every volume except `INSTALLER_CACHE`.

ISOs, OCI images, and pinned VM scripts are outside this action and retain their own acquisition
and review paths; this action no longer implies that arbitrary volumes or all artifact kinds are
updated.

## Evidence

The new cached-version comparison, download/verification, and volume-selection regressions failed
before implementation. The combined Drive Administration, web, Installer Cache, and source-lock
unit suite now passes 336 tests using scripted command results. The tests prove cache identity and
package metadata checks, the download-only command shape, archive verification, and refusal before
network work when another volume is selected. No real APT indexes were refreshed and no physical
cache volume was modified in this verification.

## Remaining work

REAL-010 remains open for publisher/version-aware update and review flows for OS images, OCI images,
curated scripts, and other non-DEB artifacts. No earlier record is superseded; this record narrows
the actual behavior of `update_selected` created by DR99.
