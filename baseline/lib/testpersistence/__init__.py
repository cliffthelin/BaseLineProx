"""TestPersistence Milestone 2 - pure schema/state-machine code only.

See docs/design/testpersistence-prd.md. No disk I/O, no LUKS, no QEMU,
no subprocess, no privilege operations anywhere in this package - every
module here is pure Python, synthetic identifiers only.
"""
