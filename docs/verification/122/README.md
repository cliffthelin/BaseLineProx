# DR122 recovery evidence

`live-recovery.json` records actual authenticated application jobs/inspection and
retained-document checks on disposable Proxmox-in-KVM, not bare-metal deployment.
CT126/base102 are the Alpine proof environment. A test-only native command shim
paused before clone (after actual OS deletion) and after native clone (before
configuration); service restarts interrupted both jobs. Explicit review and
Recover rebuild completed both. The second clone was kept through the native
description-encoding fix, without repeated rebuild. The shim was removed afterward.

The first boundary's check was observed in the initial run; final JSON includes
the second run's saved interrupted job and completed recovery/shutdown outcomes.
A stale synthetic reservation at actual119 was refused, valid openSUSE base
config unchanged. /home/job-proof retained job-retained-document. Final service
restart retained completed recoveries. No user credential/password hash included.

Final complete guarded suite: 2,882 tests passed in 126.72s. Source hashes identify final modules/tests.
This does not prove in-flight native task cancellation, host power loss, ZFS or
physical named-volume deployment. Earlier DR121/117/118 evidence stays historical.
