"""Evidence-gated ΩMEMORY vector-engine selection for MƐTAFLOW Ω.

Compact and Balanced indexes always occupy separate namespaces. Selection is
based on explicit qualification evidence, never on device class alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .rust_vector import RustVectorConfig, RustVectorIndex


class OmegaMemoryProfile(StrEnum):
    NANO = "NANO"
    EDGE = "EDGE"
    BALANCED = "BALANCED"
    PRO = "PRO"
    SOVEREIGN = "SOVEREIGN"


class VectorEngine(StrEnum):
    BALANCED = "OMEGA-VECTOR-RS"
    COMPACT = "OMEGA-VECTOR-RS-COMPACT"


@dataclass(frozen=True, slots=True)
class EngineQualification:
    compact_ci_green: bool = False
    tenant_isolation_equivalent: bool = False
    recall_loss_absolute: float | None = None
    persisted_bytes_ratio_vs_balanced: float | None = None
    p95_latency_ratio_vs_balanced: float | None = None
    evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class VectorEnginePaths:
    balanced_library: Path
    compact_library: Path


@dataclass(frozen=True, slots=True)
class VectorEngineDecision:
    profile: OmegaMemoryProfile
    engine: VectorEngine
    qualified: bool
    fallback_used: bool
    reasons: tuple[str, ...]
    evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class _ProfileGate:
    max_recall_loss: float
    max_persisted_ratio: float
    max_p95_ratio: float


_COMPACT_GATES = {
    OmegaMemoryProfile.NANO: _ProfileGate(
        max_recall_loss=0.10,
        max_persisted_ratio=0.65,
        max_p95_ratio=1.25,
    ),
    OmegaMemoryProfile.EDGE: _ProfileGate(
        max_recall_loss=0.05,
        max_persisted_ratio=0.65,
        max_p95_ratio=1.20,
    ),
}


def _coerce_profile(profile: OmegaMemoryProfile | str) -> OmegaMemoryProfile:
    if isinstance(profile, OmegaMemoryProfile):
        return profile
    return OmegaMemoryProfile(str(profile).upper())


def select_vector_engine(
    profile: OmegaMemoryProfile | str,
    qualification: EngineQualification | None = None,
) -> VectorEngineDecision:
    """Select the smallest qualified engine without weakening isolation.

    BALANCED/PRO/SOVEREIGN always use the f16-reranked engine in the current
    controlled baseline. NANO/EDGE may use Compact only when all preliminary
    profile gates have explicit evidence; missing evidence causes fallback.
    """

    resolved = _coerce_profile(profile)
    if resolved not in _COMPACT_GATES:
        return VectorEngineDecision(
            profile=resolved,
            engine=VectorEngine.BALANCED,
            qualified=True,
            fallback_used=False,
            reasons=("profile requires BALANCED q8+f16 engine",),
            evidence_ref=qualification.evidence_ref if qualification else None,
        )

    evidence = qualification or EngineQualification()
    gate = _COMPACT_GATES[resolved]
    reasons: list[str] = []

    if not evidence.compact_ci_green:
        reasons.append("Compact CI evidence is not green")
    if not evidence.tenant_isolation_equivalent:
        reasons.append("tenant-isolation equivalence is not evidenced")
    if evidence.recall_loss_absolute is None:
        reasons.append("recall-loss evidence is missing")
    elif evidence.recall_loss_absolute > gate.max_recall_loss:
        reasons.append(
            f"recall loss {evidence.recall_loss_absolute:.6f} exceeds {gate.max_recall_loss:.6f}"
        )
    if evidence.persisted_bytes_ratio_vs_balanced is None:
        reasons.append("persisted-size ratio evidence is missing")
    elif evidence.persisted_bytes_ratio_vs_balanced > gate.max_persisted_ratio:
        reasons.append(
            "persisted-size ratio "
            f"{evidence.persisted_bytes_ratio_vs_balanced:.6f} exceeds "
            f"{gate.max_persisted_ratio:.6f}"
        )
    if evidence.p95_latency_ratio_vs_balanced is None:
        reasons.append("p95 latency-ratio evidence is missing")
    elif evidence.p95_latency_ratio_vs_balanced > gate.max_p95_ratio:
        reasons.append(
            f"p95 latency ratio {evidence.p95_latency_ratio_vs_balanced:.6f} exceeds "
            f"{gate.max_p95_ratio:.6f}"
        )

    if reasons:
        return VectorEngineDecision(
            profile=resolved,
            engine=VectorEngine.BALANCED,
            qualified=False,
            fallback_used=True,
            reasons=tuple(reasons),
            evidence_ref=evidence.evidence_ref,
        )

    return VectorEngineDecision(
        profile=resolved,
        engine=VectorEngine.COMPACT,
        qualified=True,
        fallback_used=False,
        reasons=("all Compact preliminary engineering gates passed",),
        evidence_ref=evidence.evidence_ref,
    )


def profile_vector_config(
    profile: OmegaMemoryProfile | str,
    *,
    dimensions: int,
) -> RustVectorConfig:
    resolved = _coerce_profile(profile)
    if resolved is OmegaMemoryProfile.NANO:
        return RustVectorConfig(
            dimensions=dimensions,
            max_neighbors=8,
            ef_construction=48,
            ef_search=40,
            rerank_candidates=16,
            query_memory_budget_mb=2,
            max_results=6,
            max_excerpt_chars=600,
        )
    if resolved is OmegaMemoryProfile.EDGE:
        return RustVectorConfig(
            dimensions=dimensions,
            max_neighbors=10,
            ef_construction=64,
            ef_search=56,
            rerank_candidates=24,
            query_memory_budget_mb=4,
            max_results=8,
            max_excerpt_chars=800,
        )
    if resolved is OmegaMemoryProfile.PRO:
        return RustVectorConfig(
            dimensions=dimensions,
            max_neighbors=16,
            ef_construction=160,
            ef_search=128,
            rerank_candidates=96,
            query_memory_budget_mb=16,
            max_results=16,
            max_excerpt_chars=1600,
        )
    # SOVEREIGN intentionally inherits BALANCED vector tuning while applying
    # stronger isolation/persistence controls elsewhere in ΩMEMORY.
    return RustVectorConfig(
        dimensions=dimensions,
        max_neighbors=12,
        ef_construction=96,
        ef_search=80,
        rerank_candidates=48,
        query_memory_budget_mb=8,
        max_results=12,
        max_excerpt_chars=1200,
    )


def engine_namespace(root: str | Path, decision: VectorEngineDecision) -> Path:
    """Return an engine-specific index namespace; never reuse cross-format files."""

    suffix = "compact-q8" if decision.engine is VectorEngine.COMPACT else "balanced-q8-f16"
    return Path(root) / decision.profile.value.lower() / suffix


def open_profiled_vector_index(
    *,
    profile: OmegaMemoryProfile | str,
    dimensions: int,
    qualification: EngineQualification | None,
    libraries: VectorEnginePaths,
    index_root: str | Path,
) -> tuple[RustVectorIndex, VectorEngineDecision]:
    """Open the evidence-selected engine using the shared ABI adapter."""

    decision = select_vector_engine(profile, qualification)
    config = profile_vector_config(decision.profile, dimensions=dimensions)
    library_path = (
        libraries.compact_library
        if decision.engine is VectorEngine.COMPACT
        else libraries.balanced_library
    )
    index = RustVectorIndex(
        library_path=library_path,
        index_path=engine_namespace(index_root, decision),
        config=config,
    )
    return index, decision
