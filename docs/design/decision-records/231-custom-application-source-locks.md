# DR231 — Custom applications use checksum-locked package sources

**Status:** Implemented; third-party package acquisition and runtime remain unverified  
**Date:** 2026-10-09

## Context

The Installer Plan could save a custom application definition, but the
`baseline-apps` process did not reload that catalog after restart. Its native
preparation path also used a ChatGPT download URL as the fallback for other
non-built-in applications. A saved custom application therefore did not have a
reliable native acquisition path.

## Decision

Custom definitions must provide an application ID, display name, Debian package
name, safe relative executable path, exact credential-free HTTPS `.deb` URL,
and lowercase SHA256. The saved catalog is loaded through the same source-root
resolver used by installer input preparation, both by the web catalog view and
by `baseline-apps` before it builds application choices. Preparation downloads
the exact URL, verifies the declared digest, and checks the Debian package
identity, amd64 architecture, and version before binding the recipe. Unknown
applications without a registered source adapter fail explicitly.

## Evidence and scope

Four focused application-bundle contract tests passed, including catalog source
resolution/registration, HTTPS and digest validation, and Debian package
metadata checks. The test uses a context-managed temporary directory and leaves
no test directory behind. `baseline/bin/baseline-apps --help` ran successfully
against the current source tree. No FakeRunner/FakeProc was used. No external
custom package was downloaded, installed, launched, or tested in a VM; no
physical machine or drive was accessed.

## Remaining work

Wire publisher-locked custom package acquisition into Installer Plan input
preparation and prove a real publisher download, package installation, and
guest launch. Continue queue item 76; application isolation, retained data,
guest behavior, and physical deployment remain open under rows 72–76 and 78.
