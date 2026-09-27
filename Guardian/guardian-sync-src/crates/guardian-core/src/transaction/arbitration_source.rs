//! `ArbitrationStateSource` -- the G4-owned authority for `revision` (G4
//! handoff §7). G3's `arbitrate()` is a pure function that only carries a
//! supplied `revision` through unchanged; it is NOT the source of
//! revision. This trait is that source: G4's engine calls it to obtain the
//! current revision/candidate set for a capability, builds
//! `ArbitrationInput` from that, and only then calls `arbitrate()`. A
//! transaction caller never supplies the authoritative revision.

use guardian_provider_api::CapabilityId;

use crate::arbitration::CandidateProvider;

pub trait ArbitrationStateSource {
    fn current_revision(&self, capability_id: &CapabilityId) -> u64;
    fn current_candidates(&self, capability_id: &CapabilityId) -> Vec<CandidateProvider>;
}
