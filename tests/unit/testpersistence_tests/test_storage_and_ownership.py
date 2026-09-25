"""Storage-class namespace mapping (PRD §3) and ownership/recovery
authority separated from application grants (PRD §5, §8)."""
from testpersistence.ownership import RecoveryAuthority, can_authorize_import
from testpersistence.storage_classes import (
    StorageClass, migrates_with_logical_store, namespaces_for,
)


def test_cache_class_has_no_manifest_namespace():
    assert namespaces_for(StorageClass.CACHE) == ()
    assert migrates_with_logical_store(StorageClass.CACHE) is False


def test_disposable_substrate_does_not_migrate_with_logical_store():
    assert migrates_with_logical_store(StorageClass.DISPOSABLE_SUBSTRATE) is False


def test_person_and_application_classes_migrate_with_logical_store():
    assert migrates_with_logical_store(StorageClass.PERSON) is True
    assert migrates_with_logical_store(StorageClass.APPLICATION) is True


def test_secrets_have_their_own_namespace_not_shared_with_person_or_application():
    secrets_ns = set(namespaces_for(StorageClass.SECRETS))
    person_ns = set(namespaces_for(StorageClass.PERSON))
    application_ns = set(namespaces_for(StorageClass.APPLICATION))
    assert secrets_ns.isdisjoint(person_ns)
    assert secrets_ns.isdisjoint(application_ns)


# --- ownership/recovery authority, separate from application grants -------

def test_recovery_authority_holder_can_authorize_import():
    authority = RecoveryAuthority(held_by="TestPerson-001", mechanism="test-passphrase-placeholder")
    assert can_authorize_import(authority, requester="TestPerson-001")


def test_non_holder_cannot_authorize_import_even_with_an_application_grant():
    """An application grant, however broad, is never sufficient to
    authorize importing the store itself - only the recovery-authority
    holder can (PRD §5, §8)."""
    authority = RecoveryAuthority(held_by="TestPerson-001", mechanism="test-passphrase-placeholder")
    assert not can_authorize_import(authority, requester="TestApplication-A")
    assert not can_authorize_import(authority, requester="TestPerson-002")
