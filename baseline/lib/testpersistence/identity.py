"""Logical-store vs. carrier identity (PRD §4) - two independent axes,
never conflated. A logical store's carrier can change (authorized
migration to replacement hardware); its logical identity does not."""
import dataclasses


@dataclasses.dataclass(frozen=True)
class CarrierIdentity:
    """The specific virtual/physical disk currently carrying a store.
    Never used as, or compared against, logical identity - naming a
    logical store after its current carrier reintroduces exactly the
    hardware/logical coupling this model exists to break."""
    carrier_id: str
    gpt_disk_guid: str = ""
    luks_uuid: str = ""
    filesystem_uuid: str = ""


@dataclasses.dataclass(frozen=True)
class LogicalStoreIdentity:
    """Baseline's own concept of "the same store" - survives an
    authorized migration to a different carrier (PRD §4)."""
    logical_id: str
    generation: int


def is_same_logical_store(a: LogicalStoreIdentity, b: LogicalStoreIdentity) -> bool:
    """Equivalence is about logical_id only. A differing generation is
    continuity (the same store legitimately evolved forward), not a
    different store - see evidence.evaluate_identity for how a
    *conflicting* generation claim is handled instead."""
    return a.logical_id == b.logical_id
