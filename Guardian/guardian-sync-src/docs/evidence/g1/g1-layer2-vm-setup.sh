#!/bin/bash
# Reproducible setup for G1 Layer 2 (real-host) evidence, run inside a
# disposable Ubuntu 26.04.1 VM only — never on a primary development
# workstation (AGENTS.md; G1 handoff §5.2, §13).
#
# This is the exact sequence used to produce
# docs/evidence/g1/g1_layer2_server_transcript.log and the P0-AUTH-001/002/003
# real-host results reported in docs/evidence/g1/G1_LAYER2_EVIDENCE.md.
#
# Usage (from a fresh Ubuntu 26.04.1 VM with this repository copied to
# /home/ubuntu/guardian-plane):
#   bash docs/evidence/g1/g1-layer2-vm-setup.sh
set -euxo pipefail

REPO=/home/ubuntu/guardian-plane
HARNESS="$REPO/tests/vm/g1-layer2"

sudo apt-get update -qq
sudo apt-get install -y -qq rustc cargo expect sshpass openssh-server

(cd "$HARNESS" && cargo build)

# --- D-Bus system-bus policy: allow the harness to own its well-known name
#     and allow any local sender to call it (authorization is polkit's job,
#     not bus policy's — TDD contract §7.5) ---
sudo tee /etc/dbus-1/system.d/io.github.cliffthelin.Guardian1.G1LayerTwoHarness.conf > /dev/null <<'EOF'
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="root">
    <allow own="io.github.cliffthelin.Guardian1.G1LayerTwoHarness"/>
  </policy>
  <policy context="default">
    <allow send_destination="io.github.cliffthelin.Guardian1.G1LayerTwoHarness"/>
  </policy>
</busconfig>
EOF
# NOT `systemctl restart dbus`: restarting the bus daemon process itself
# severs every other service's existing connection to it (systemd-logind,
# polkitd, ...) without them reliably reconnecting, which silently breaks
# session tracking for the rest of this script. `reload` runs dbus-daemon's
# own ReloadConfig over the existing process instead.
sudo systemctl reload dbus

# --- polkit action definitions: the four G1 test actions (TDD contract §9).
#     moderate-write requires interactive self-authentication; the other
#     three have no implicit grant at all, so only the rules.d file below can
#     authorize them.
#
#     moderate-write sets all three of allow_any/allow_inactive/allow_active
#     to auth_self, not just allow_active. Root cause found the hard way:
#     polkit classifies a session with no seat (which includes every SSH
#     session, since remote logins are never seat-attached) under
#     allow_any, not allow_active or allow_inactive — allow_active alone
#     left allow_any at its default "no", which is a hard, unchallengeable
#     deny for exactly the session type this test needs to exercise
#     (TDD contract §8.4's "VT/recovery-style non-graphical session").
#     Confirmed empirically: with only allow_active=auth_self, even
#     `pkcheck --enable-internal-agent --allow-user-interaction` over SSH
#     never showed a prompt; setting allow_any=auth_self as well produced a
#     real password challenge on the first attempt. ---
sudo tee /usr/share/polkit-1/actions/io.github.cliffthelin.guardian.test.policy > /dev/null <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <vendor>Guardian Plane G1 harness</vendor>
  <action id="guardian.test.read">
    <description>Guardian G1 test action: read</description>
    <message>Guardian G1 test read</message>
    <defaults><allow_any>no</allow_any><allow_inactive>no</allow_inactive><allow_active>no</allow_active></defaults>
  </action>
  <action id="guardian.test.low-risk-write">
    <description>Guardian G1 test action: low-risk write</description>
    <message>Guardian G1 test low-risk write</message>
    <defaults><allow_any>no</allow_any><allow_inactive>no</allow_inactive><allow_active>no</allow_active></defaults>
  </action>
  <action id="guardian.test.moderate-write">
    <description>Guardian G1 test action: moderate-risk write</description>
    <message>Guardian G1 test moderate-risk write</message>
    <defaults><allow_any>auth_self</allow_any><allow_inactive>auth_self</allow_inactive><allow_active>auth_self</allow_active></defaults>
  </action>
  <action id="guardian.test.high-risk-write">
    <description>Guardian G1 test action: high-risk write</description>
    <message>Guardian G1 test high-risk write</message>
    <defaults><allow_any>no</allow_any><allow_inactive>no</allow_inactive><allow_active>no</allow_active></defaults>
  </action>
</policyconfig>
EOF

# --- polkit rule: grant guardiang01 read + low-risk-write explicitly. Every
#     other (user, action) pair falls through to the implicit "no" defaults
#     above, i.e. is denied purely by real polkit, not by anything Guardian
#     itself decided. ---
sudo tee /etc/polkit-1/rules.d/50-guardian-g1-test.rules > /dev/null <<'EOF'
polkit.addRule(function(action, subject) {
    if (action.id == "guardian.test.low-risk-write" && subject.user == "guardiang01") {
        return polkit.Result.YES;
    }
    if (action.id == "guardian.test.read" && subject.user == "guardiang01") {
        return polkit.Result.YES;
    }
});
EOF
sudo systemctl restart polkit

# --- two real, distinct local users: guardiang01 (granted low-risk-write),
#     guardiang02 (granted nothing) ---
sudo useradd -m -s /bin/bash guardiang01 || true
sudo useradd -m -s /bin/bash guardiang02 || true
echo "guardiang01:testpass123" | sudo chpasswd

# --- allow password SSH for this disposable VM only, so guardiang01 gets a
#     real logind session (required for any interactive-auth path at all) ---
sudo sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' \
  /etc/ssh/sshd_config.d/60-cloudimg-settings.conf 2>/dev/null || true
sudo systemctl restart ssh

echo "setup complete"
