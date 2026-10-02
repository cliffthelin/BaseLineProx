# DR125 — Application overlay plan path validation

Date: 2026-10-02. Accepted. Narrows DR119 planner defects and queue74.

## Change

Before applying the first guest application, remove two known planner defects.
Overlay state directory names now use reversible UTF-8 hex encoding, so a dash
and a path separator cannot collide. Targets are normalized lexically before
planning; relative paths, other-user tildes, parent traversal, root/home-root,
control characters and mount-option delimiters are refused. Encoded components
over 255 bytes are explicitly refused. Equivalent and ancestor/descendant mount
targets are reported as conflicts, including nested targets within one app.
Container-internal binds remain a separate namespace and are not compared as
host overlay targets. No existing data is moved or deleted.

This changes generated preview paths. There is no shipped apply lifecycle or
runtime app data to migrate from this planner; custom external users of its
previous generated paths must reconcile them before applying. No implicit
migration, mounting, account creation or success stub is added.

## Evidence and scope

Public plan generation reproduced ~/a-b versus ~/a/b sharing upper/work;
the regression failed before the encoding fix. Separate RED/GREEN cycles cover
nested/equivalent targets, unsafe mount input, normalized roots and excessive
component length. All 67 appdata unit tests passed with real pure planner code;
no fake native mount or runtime success was claimed. Provision import staging
and whitespace checks passed. No hardware, credentials, VM boot, live sandbox
or physical storage operations were performed for this increment.

## Remaining work and historical continuity

Queue74 stays open: unknown versus explicitly stateless declarations, selected
mounted AppData identity, canonical runtime/symlink resolution, non-login app
identity, actual profile migration, trusted registry separation, namespace launch,
explicit sharing, two-app denial proof, rebuild/reset/update and recovery.
Quadlet mounted/disposable-volume checks are also still open. The first
Chromium/Ubuntu runtime lifecycle remains the next applied-app goal. Lexical
normalization here does not establish real filesystem or permission isolation.

The DR119 audit findings remain historical; current audit follow-up, INSTALL,
queue and handoff are corrected in place. DR124 retained-container restore is
unchanged and does not prove per-app confinement. AI is not a runtime dependency.

Guarded regression suite: **2,908 passed in 126.83s**, collected before the final
normalized-root/length test. Final focused suite covers that addition: 67 passed.
Implementation commit: 6b92012. No runtime app confinement claim.
