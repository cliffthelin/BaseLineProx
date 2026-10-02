# DR121 verification

`live-jobs.json` records actual authenticated HTTP/native Proxmox outcomes,
including snapshots of the same interrupted job before and after inspection and
review. `workload-page.html` captures the authenticated jobs page after proof.
CT126 is the stopped Alpine proof container, base102 its immutable template.
/home/job-proof survived login rotation and the fresh explicit clean rebuild.

This is actual Proxmox in a disposable KVM clone, with the serial-validated
physical backing read-only and all mutations in its qcow2 overlay. Not bare-metal
deployment. The interruption occurred during rebuild preflight, before deletion.
No claim of mid-destruction, orphan repair or power-loss recovery.

2,874 guarded unit tests passed in 119.68s. The final stage-preservation/lease
fix was unit-tested and copied into the clone after the first interrupted-job
snapshot, so that historical snapshot has no last_observed_stage field.
Source hashes describe final files, not a retroactive claim that every live
snapshot exercised every later line. Cleartext logins and password hashes are
excluded. Source/fixture credentials remain private and are not included.
