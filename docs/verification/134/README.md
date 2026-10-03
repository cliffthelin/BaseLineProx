# DR134 verification

2993 unit tests passed in149.88s. Native Ansible Core2.21.4 / Runner2.4.3
ran the registered prerequisite and suite roles in actual disposable KVM guests.
Debian13.7 recorded installed dependencies and five locked apps; Ubuntu24.04.5
recorded installed dependencies and Chrome. Both final repeats reported changed=0.
Target source ownership/permissions and backend hashes were verified by the roles.
The summary contains scoped successful observations, not raw inventories, SSH
keys, profiles, login credentials or Runner logs. Earlier failures remain private
Runner artifacts and failed database rows; none were promoted to compatibility.
DR133 separately documents native GUI/retained-root proofs. No physical writes.

The final manual Proxmox ISO independently extracted467 staged files with all
SHA256 values matching its clean source snapshot. installer-manifest.json records
its checksum, publisher source and release-signature fingerprints. No unattended
answer/password hash is embedded. Installer menu boot alone is not installation.
The manifest is published beside the ISO rather than inside it (self-checksum
would be circular). Private source images/credentials were never staged.

Final artifact boot screenshot is from KVM CPU host/one vCPU. Default CPU/two
vCPUs stalled with a black display; the cause remains undiagnosed. This failed
attempt is retained and is not counted as verified boot.
