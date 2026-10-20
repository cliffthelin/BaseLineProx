# DR202: Remove nonfunctional hardware-modal panes and save action

Date: 2026-10-09  
Status: accepted

## Context

The Textual hardware modal displayed Description, Troubleshooting, Logs, and
Configuration panes containing only static “not configured” text. Its Save
and Close button dismissed the modal without saving anything. Those controls
looked like implemented functionality but had no data source or effect.

## Decision

The modal shows only the collected hardware fields and a Close button. It no
longer exposes empty panes, tab navigation, or a no-op save action. A real
configuration or troubleshooting feature can be added when it has a device
specific data source and a tested action path.

## Evidence

A regression test failed before the change because the modal's compose method
contained `TabbedContent` and the Save button. After the change it asserts the
only modal button is Close and no tabbed placeholder surface remains. The test
parses the real source AST because Textual/Rich are not installed in the test
environment; it does not claim a live TUI render. The combined focused suite
passed 98 tests (AppData, harness registry, OpenCode adapter, and this modal
contract). No physical hardware was changed.

## Remaining work

The modal remains read-only. Device specific configuration, troubleshooting,
and logs require real actions and sources before they can be offered. No
earlier decision record is superseded.
