# DR215: Audit log read errors are not empty history

**Status:** Accepted  
**Date:** 2026-10-09

## Context

`audit_view.read_tail()` treated every `OSError` as a missing file. An unreadable
or unavailable audit log therefore looked like a valid empty history on the
Audit and Operations pages.

## Decision

A genuinely missing audit file remains an empty history. Other read failures
raise `AuditReadError`. The Audit page responds with HTTP 503 and an explicit
diagnostic; the Operations page labels its history unavailable instead of
showing "No recorded runs," and the JSON history endpoint returns HTTP 503.
An absent configured audit path is also reported as unavailable.

## Evidence and scope

The audit/approvals, operations, and operations-web suite passed 85 tests. The
new regressions inject permission failures and exercise the local web routes.
No host audit log was read or changed.

## Remaining work

This does not validate real audit-log integrity, retention, or tamper response.
It only makes read failures visible instead of presenting them as an empty log.
