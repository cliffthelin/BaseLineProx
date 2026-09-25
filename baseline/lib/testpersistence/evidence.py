"""Multi-evidence identity model (PRD §4). Identity is a body of
time-scoped evidence, never one identifier. EvidenceClaim records one
piece of evidence about a claim (carrier identity, logical identity, or
generation); evaluate_identity composes multiple claims for the same
scope and produces an explicit outcome - never a best guess - when they
conflict."""
import dataclasses
import enum


class EvidenceScope(enum.Enum):
    CARRIER_IDENTITY = "carrier_identity"
    LOGICAL_IDENTITY = "logical_identity"
    GENERATION = "generation"


class Confidence(enum.Enum):
    DIRECTLY_READ = "directly_read"
    INFERRED = "inferred"
    EXTERNALLY_REPORTED = "externally_reported"


class CorroborationStatus(enum.Enum):
    UNCORROBORATED = "uncorroborated"
    CORROBORATING = "corroborating"
    CONTRADICTING = "contradicting"


@dataclasses.dataclass(frozen=True)
class EvidenceClaim:
    source: str  # e.g. "luks_header", "manifest_field", "external_observation"
    observation_time: float  # a synthetic clock value in tests, never assumed current
    scope: EvidenceScope
    value: str
    confidence: Confidence
    corroboration: CorroborationStatus = CorroborationStatus.UNCORROBORATED


class IdentityOutcome(enum.Enum):
    EQUIVALENT = "equivalent"
    AMBIGUOUS_REFUSAL = "ambiguous_refusal"


@dataclasses.dataclass(frozen=True)
class IdentityEvaluation:
    outcome: IdentityOutcome
    scope: EvidenceScope
    reason: str


def evaluate_identity(scope: EvidenceScope, claims: list) -> IdentityEvaluation:
    """Given multiple EvidenceClaims about the same scope, decide
    equivalence vs. an explicit ambiguous/refusal outcome (PRD §4's
    "conflicting evidence produces an explicit ambiguous/refusal
    state"). Never resolved by a best guess or majority vote: if two
    directly-read claims for the same scope disagree, that is
    ambiguous_refusal regardless of how many claims agree with either
    one."""
    relevant = [c for c in claims if c.scope == scope]
    if not relevant:
        return IdentityEvaluation(IdentityOutcome.AMBIGUOUS_REFUSAL, scope,
                                   "no evidence for this scope")
    values = {c.value for c in relevant}
    if len(values) > 1:
        return IdentityEvaluation(
            IdentityOutcome.AMBIGUOUS_REFUSAL, scope,
            f"conflicting evidence values for {scope.value}: "
            f"{len(values)} distinct values across {len(relevant)} claim(s)")
    return IdentityEvaluation(IdentityOutcome.EQUIVALENT, scope,
                               f"{len(relevant)} claim(s) agree")
