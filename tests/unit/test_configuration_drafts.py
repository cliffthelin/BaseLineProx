import pytest
from configuration_drafts import DraftStore, DraftError, DraftConflict


def test_drafts_survive_reopen_and_are_owned_by_authenticated_user(tmp_path):
    path = tmp_path / 'drafts.sqlite'
    store = DraftStore(path)
    saved = store.save('alice', 'installer', {'environment': {'variant': 'server'}}, expected_revision=0)
    assert saved['revision'] == 1 and saved['applied'] is False
    reopened = DraftStore(path)
    assert reopened.get('alice', 'installer')['document']['environment']['variant'] == 'server'
    assert reopened.get('bob', 'installer') is None
    assert len(reopened.list('alice')) == 1


def test_stale_editor_cannot_overwrite_newer_draft(tmp_path):
    store = DraftStore(tmp_path / 'drafts.sqlite')
    store.save('alice', 'recipe', {'document': {'id': 'ubuntu'}, 'app_document': None}, expected_revision=0)
    with pytest.raises(DraftConflict):
        store.save('alice', 'recipe', {'document': {'id': 'stale'}, 'app_document': None}, expected_revision=0)
    assert store.get('alice', 'recipe')['document']['document']['id'] == 'ubuntu'


@pytest.mark.parametrize('document', [[], {'large': 'x'*65536}, {'source': {'password': 'forbidden'}}, {'x': float('nan')}])
def test_invalid_or_secret_payload_refused_without_persistence(tmp_path, document):
    store = DraftStore(tmp_path / 'drafts.sqlite')
    with pytest.raises(DraftError):
        store.save('alice', 'installer', document, expected_revision=0)
    assert store.get('alice', 'installer') is None


def test_failed_transaction_preserves_prior_revision_and_private_file_mode(tmp_path):
    path = tmp_path / 'drafts.sqlite'
    store = DraftStore(path)
    store.save('alice', 'installer', {'environment': {'name': 'kept'}}, expected_revision=0)
    with pytest.raises(DraftError):
        store.save('alice', 'installer', {'x': float('inf')}, expected_revision=1)
    assert store.get('alice', 'installer')['revision'] == 1
    assert path.stat().st_mode & 0o777 == 0o600


def test_recipe_draft_requires_editor_envelope(tmp_path):
    store = DraftStore(tmp_path / 'drafts.sqlite')
    with pytest.raises(DraftError):
        store.save('alice', 'recipe', {'unrelated': {}}, expected_revision=0)
