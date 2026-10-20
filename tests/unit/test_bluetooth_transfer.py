"""Parent Bluetooth transfer uses real temporary files; no controller is exercised."""
from pathlib import Path


def test_parent_pairings_are_copied_to_private_persistent_storage(tmp_path):
    import bluetooth_transfer as bt
    parent = tmp_path / 'parent'
    info = parent / 'AA:BB:CC:DD:EE:FF' / '11:22:33:44:55:66' / 'info'
    info.parent.mkdir(parents=True)
    info.write_text('[General]\nName=Test keyboard\n')
    admin = tmp_path / 'USER_ADMIN'
    admin.mkdir()
    result = bt.seed(parent, admin)
    target = admin / 'var-lib-bluetooth'
    assert (target / info.relative_to(parent)).read_bytes() == info.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o700
    assert result['state'] == 'copied'
    assert bt.seed(parent, admin)['state'] == 'already present'


def test_host_pairings_are_persistent_and_migration_requires_stopped_bluez():
    import persist_bind_mounts as pbm
    assert pbm.REDIRECT_PATHS['/var/lib/bluetooth'] == 'var-lib-bluetooth'
    assert pbm.QUIESCE_BEFORE_MOVE['/var/lib/bluetooth'] == ('bluetooth',)


def test_transfer_refuses_conflicts_empty_sources_and_links(tmp_path):
    import pytest
    import bluetooth_transfer as bt
    parent = tmp_path / 'parent'
    parent.mkdir()
    admin = tmp_path / 'admin'
    admin.mkdir()
    with pytest.raises(bt.TransferError, match='no stored'):
        bt.seed(parent, admin)
    info = parent / 'AA:BB:CC:DD:EE:FF' / '11:22:33:44:55:66' / 'info'
    info.parent.mkdir(parents=True)
    info.write_text('synthetic old')
    bt.seed(parent, admin)
    info.write_text('synthetic changed')
    with pytest.raises(bt.TransferError, match='different'):
        bt.seed(parent, admin)
    info.unlink()
    info.symlink_to(tmp_path / 'outside')
    with pytest.raises(bt.TransferError, match='link'):
        bt.seed(parent, admin)


def test_saved_plan_only_transfers_when_selected(tmp_path):
    import bluetooth_transfer as bt
    assert bt.apply_plan({}, tmp_path) == {'state': 'not requested'}
    import pytest
    with pytest.raises(bt.TransferError, match='boolean'):
        bt.apply_plan({'host_configuration': {'bluetooth_from_parent': 'yes'}}, tmp_path)
    source = tmp_path / 'source'
    info = source / 'AA:BB:CC:DD:EE:FF/11:22:33:44:55:66/info'
    info.parent.mkdir(parents=True)
    info.write_text('synthetic pairing')
    admin = tmp_path / 'admin'
    admin.mkdir()
    assert bt.apply_plan({'host_configuration': {'bluetooth_from_parent': True}}, admin, source=source)['state'] == 'copied'


def test_empty_first_boot_directory_can_receive_parent_pairings(tmp_path):
    import bluetooth_transfer as bt
    source = tmp_path / 'parent'
    info = source / 'AA:BB:CC:DD:EE:FF/11:22:33:44:55:66/info'
    info.parent.mkdir(parents=True)
    info.write_text('synthetic')
    admin = tmp_path / 'admin'
    (admin / 'var-lib-bluetooth').mkdir(parents=True)
    assert bt.seed(source, admin)['state'] == 'copied'
