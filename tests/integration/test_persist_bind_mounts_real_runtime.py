"""RealRunner checks for mount-state and fstab observation.

These tests read the kernel's live mount table and real temporary files. They
do not mount, format, probe, or modify any physical drive.
"""
import pytest

import persist_bind_mounts as pbm
import settings_web
from repair import RealRunner


def test_real_runner_observes_kernel_root_mount_and_absent_mountpoint():
    runner=RealRunner()
    assert pbm.is_mounted(runner,'/') is True
    assert pbm.is_mounted(runner,'/baseline-audit-path-that-is-not-mounted') is False
    root_line=next(line for line in runner.read_text('/proc/self/mounts').splitlines()
                   if len(line.split())>=4 and line.split()[1]=='/')
    assert pbm.is_mounted_read_write(runner,'/')==('rw' in root_line.split()[3].split(','))


def test_real_runner_surfaces_mount_table_read_error():
    runner=RealRunner()
    with pytest.raises(pbm.PersistenceObservationError,match='mount table'):
        pbm.is_mounted(runner,'/',mount_table_path='/proc/self')


def test_real_runner_reads_fstab_content_and_surfaces_read_error():
    runner=RealRunner()
    assert pbm._fstab_has_line(runner,'BASELINE_AUDIT_ENTRY_NOT_PRESENT',fstab_path='/etc/fstab') is False
    with pytest.raises(pbm.PersistenceObservationError,match='cannot inspect'):
        pbm._fstab_has_line(runner,'BASELINE_AUDIT_ENTRY_NOT_PRESENT',fstab_path='/proc/self')


def test_recovery_handlers_return_visible_error_when_mount_table_cannot_be_read():
    runner=RealRunner()
    view=settings_web.handle_recovery_view(
        runner,personas=('primary',),mount_table_path='/proc/self')
    assert view.status==503
    assert 'kernel mount table' in view.body['error']

    exit_result=settings_web.handle_recovery_exit(
        runner,personas=('primary',),now=1,mount_table_path='/proc/self')
    assert exit_result.status==503
    assert 'kernel mount table' in exit_result.body['error']


def test_recovery_page_surfaces_corrupt_state_instead_of_reporting_inactive():
    runner=RealRunner()
    result=settings_web.handle_recovery_view(
        runner,personas=(),state_path='/proc/self/mounts')
    assert result.status==503
    assert 'recovery state' in result.body['error']


def test_real_runner_discovers_a_present_filesystem_label_from_lsblk():
    runner=RealRunner()
    device=pbm.discover_device_by_label(runner,'CACHE')
    assert isinstance(device,str) and device.startswith('/dev/')


def test_real_runner_confirms_a_unique_absent_label_from_complete_inventory():
    runner=RealRunner()
    assert pbm.discover_device_by_label(runner,'BASELINE_AUDIT_LABEL_ABSENT') is None


