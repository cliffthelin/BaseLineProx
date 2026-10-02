# DR124 verification

live-backup-restore.json records authenticated durable backup/restore jobs on
actual disposable Proxmox-in-KVM. Two new Alpine containers booted and read
retained /home, /root and /data; /etc customization was excluded. Metadata check
proved real user xattrs and POSIX ACLs, preserved first archive/original data/
unrelated destination file, and verified fresh native login without publishing
its password/hash. Completed jobs survived web-service restart. backup-page.html
is the actual final backup page. source-sha256.json identifies final source/tests.

A new ext4 virtual USB image was formatted and mounted inside the clone. No
physical disk was formatted or written. Separate virtual devices do not prove
separate physical failure domains. The final source-disk guard passed a native
read-only ancestry check; its refusal cases use fake block identities in tests.
Full VM recovery, physical off-drive proof, cross-host restore and power loss
remain open. No keys, cleartext passwords or login hashes are included.

Final guarded unit suite: **2,905 passed in 133.73s**. Provision import staging
check and git diff whitespace check passed. Unit Proxmox/drive identities are
fakes; the separate native evidence above is actual disposable KVM execution.
