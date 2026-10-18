"""Real temporary files and production mv; no mounts or fake runners."""
import json

import persist_bind_mounts as pbm
from repair import RealRunner


def test_redirect_migration_checks_a_failed_move_and_retains_a_retry_record(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "state").write_text("retain")
    target = tmp_path / "destination"
    source.chmod(0o500)
    try:
        result = pbm.migrate_redirect_contents(RealRunner(), str(source), str(target))
    finally:
        source.chmod(0o700)
    assert not result.applied
    assert (source / "state").read_text() == "retain"
    assert (tmp_path / ".destination.migration-pending").is_file()


def test_completed_migration_preserves_file_content_and_clears_the_record(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "state").write_text("retain")
    target = tmp_path / "destination"
    result = pbm.migrate_redirect_contents(RealRunner(), str(source), str(target))
    assert result.applied and not (source / "state").exists()
    assert (target / "state").read_text() == "retain"
    assert not (tmp_path / ".destination.migration-pending").exists()


def test_pending_migration_never_overwrites_a_destination_collision(tmp_path):
    source, target = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    target.mkdir()
    (source / "state").write_text("source")
    (target / "state").write_text("persisted")
    (tmp_path / ".destination.migration-pending").write_text(json.dumps({"source":str(source), "destination":str(target)}))
    result = pbm.migrate_redirect_contents(RealRunner(), str(source), str(target))
    assert not result.applied
    assert (source / "state").read_text() == "source"
    assert (target / "state").read_text() == "persisted"
