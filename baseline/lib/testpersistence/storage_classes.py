"""Storage-class taxonomy (PRD testpersistence-prd.md §3) - which
manifest namespace each class of data lives in, and its migration
policy relative to the logical store vs. the disposable substrate."""
from enum import Enum


class StorageClass(Enum):
    DISPOSABLE_SUBSTRATE = "disposable_substrate"
    CONTROL_PLANE = "control_plane"
    PERSON = "person"
    APPLICATION = "application"
    SECRETS = "secrets"
    CACHE = "cache"


# Which manifest namespaces (PRD §6) belong to which storage class.
# Classes 2-6 live inside the encrypted TestPersistence manifest;
# class 1 (disposable substrate) never does.
NAMESPACES_BY_CLASS = {
    StorageClass.CONTROL_PLANE: ("authority_ledger",),
    StorageClass.PERSON: ("person", "preferences"),
    StorageClass.APPLICATION: ("application_state", "grants"),
    StorageClass.SECRETS: ("secrets",),
    StorageClass.CACHE: (),  # never persisted in the manifest at all
}

# Whether this class's data migrates with the logical store (survives a
# carrier swap) rather than with the disposable substrate.
MIGRATES_WITH_LOGICAL_STORE = {
    StorageClass.DISPOSABLE_SUBSTRATE: False,
    StorageClass.CONTROL_PLANE: True,
    StorageClass.PERSON: True,
    StorageClass.APPLICATION: True,
    StorageClass.SECRETS: True,
    StorageClass.CACHE: False,
}


def namespaces_for(storage_class: StorageClass) -> tuple:
    return NAMESPACES_BY_CLASS.get(storage_class, ())


def migrates_with_logical_store(storage_class: StorageClass) -> bool:
    return MIGRATES_WITH_LOGICAL_STORE[storage_class]
