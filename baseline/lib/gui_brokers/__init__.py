"""Track B3's four minimal GUI brokers (see
docs/design/milestone-2-gui-plan.md) - notification, clipboard,
file_picker, plus download/export (which reuses browser_policy.py's
DownloadDirectory instead of its own module). Each is small, separately
testable, and Runner-injectable, matching decision record 29's "minimal
access-broker boundary, not a generic framework" philosophy - not a
xdg-desktop-portal replacement.
"""
