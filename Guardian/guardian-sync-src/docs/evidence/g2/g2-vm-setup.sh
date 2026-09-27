#!/bin/bash
# Reproducible setup for G2 Layer 2 (real-host) evidence, run inside a
# disposable Ubuntu 26.04.1 VM only — never on a primary development
# workstation (AGENTS.md; G2 handoff §16).
#
# Usage (from a fresh Ubuntu 26.04.1 VM with this repository copied to
# /home/ubuntu/guardian-plane):
#   bash docs/evidence/g2/g2-vm-setup.sh
set -euxo pipefail

REPO=/home/ubuntu/guardian-plane

sudo apt-get update -qq
sudo apt-get install -y -qq rustc cargo

(cd "$REPO/tests/vm/g2-model-a" && cargo build --release)
(cd "$REPO/tests/vm/g2-model-b" && cargo build --release)

sudo install -m755 "$REPO/tests/vm/g2-model-a/target/release/g2-model-a-daemon" /usr/local/bin/
sudo install -m755 "$REPO/tests/vm/g2-model-a/target/release/g2-model-a-client" /usr/local/bin/
sudo install -m755 "$REPO/tests/vm/g2-model-b/target/release/g2-model-b-core" /usr/local/bin/
sudo install -m755 "$REPO/tests/vm/g2-model-b/target/release/g2-model-b-helper" /usr/local/bin/
sudo install -m755 "$REPO/tests/vm/g2-model-b/target/release/g2-model-b-client" /usr/local/bin/

# --- dedicated service users ---
sudo useradd -r -s /usr/sbin/nologin svc-model-a || true
sudo useradd -r -s /usr/sbin/nologin svc-model-b-core || true
sudo useradd -r -s /usr/sbin/nologin svc-model-b-helper || true
# real caller identities used to exercise real polkit authorization
sudo useradd -m -s /bin/bash guardiang2caller || true
sudo useradd -m -s /bin/bash guardiang2denied || true

# --- D-Bus system-bus policy ---
#
# `root` is granted ownership of the Model A and Model B-helper names
# alongside their nominal service users: empirically, polkit's
# CheckAuthorization refuses to answer for a subject other than the caller
# itself unless the calling process is a "trusted caller" (uid 0, or the
# action's registered owner) -- confirmed the hard way this pass (see
# MODEL_A_EVIDENCE.md §"The trusted-caller finding"). Both the Model A
# daemon and the Model B helper therefore run as root (User=root in their
# unit files below), so both names need root ownership permission. The
# `svc-model-a`/`svc-model-b-helper` policy entries are kept for anyone who
# re-derives a non-root-requiring variant later.
sudo tee /etc/dbus-1/system.d/io.github.cliffthelin.Guardian1.G2.conf > /dev/null <<'EOF'
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="root">
    <allow own="io.github.cliffthelin.Guardian1.G2ModelA"/>
    <allow own="io.github.cliffthelin.Guardian1.G2ModelBHelper"/>
  </policy>
  <policy user="svc-model-a">
    <allow own="io.github.cliffthelin.Guardian1.G2ModelA"/>
  </policy>
  <policy user="svc-model-b-core">
    <allow own="io.github.cliffthelin.Guardian1.G2ModelBCore"/>
  </policy>
  <policy user="svc-model-b-helper">
    <allow own="io.github.cliffthelin.Guardian1.G2ModelBHelper"/>
  </policy>
  <policy context="default">
    <allow send_destination="io.github.cliffthelin.Guardian1.G2ModelA"/>
    <allow send_destination="io.github.cliffthelin.Guardian1.G2ModelBCore"/>
    <allow send_destination="io.github.cliffthelin.Guardian1.G2ModelBHelper"/>
  </policy>
</busconfig>
EOF
sudo systemctl reload dbus

# --- polkit action + rule (reuses the exact action id G1 tested:
#     guardian.test.low-risk-write, mapped from PolkitAction::LowRiskWrite) ---
sudo tee /usr/share/polkit-1/actions/io.github.cliffthelin.guardian.g2test.policy > /dev/null <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <vendor>Guardian Plane G2 harness</vendor>
  <action id="guardian.test.low-risk-write">
    <description>Guardian G2 bounded test write</description>
    <message>Guardian G2 bounded test write</message>
    <defaults><allow_any>no</allow_any><allow_inactive>no</allow_inactive><allow_active>no</allow_active></defaults>
  </action>
</policyconfig>
EOF
sudo tee /etc/polkit-1/rules.d/50-guardian-g2-test.rules > /dev/null <<'EOF'
polkit.addRule(function(action, subject) {
    if (action.id == "guardian.test.low-risk-write" && subject.user == "guardiang2caller") {
        return polkit.Result.YES;
    }
});
EOF
sudo systemctl restart polkit

# --- systemd units: see docs/evidence/g2/model-a/guardian-model-a.service
#     and docs/evidence/g2/model-b/guardian-model-b-{core,helper}.service
#     for the exact, real-tested unit files this pass produced. Install them
#     to /etc/systemd/system/ and `systemctl daemon-reload && systemctl start`
#     to reproduce. ---

echo 'g2 setup complete (install the three .service files separately, see above)'
