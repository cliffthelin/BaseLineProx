# DR127 verification

11 focused tests passed in0.15s. Real parser/CLI subprocesses, no native VM or
mount tests. Synthetic-stack.json is actual compose output verified by the CLI.
Its repeated a/b hashes are synthetic test identities, not downloadable images
or trustworthy publisher references. It is not an installable environment.
No private data, password/hash, device identity or host paths are included.
Source hashes identify final code/tests/provision. No hardware/credential work.
Provision import staging and whitespace checks passed. See DR127 for limits.

Final guarded regression suite: **2,920 passed in 131.65s**. Implementation
commit5d1cc39. Unit/runtime claims remain separated as documented above.
