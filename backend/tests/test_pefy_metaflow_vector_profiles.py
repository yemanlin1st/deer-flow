from pathlib import Path

from deerflow.pefy_omega.vector_profiles import (
    EngineQualification,
    OmegaMemoryProfile,
    VectorEngine,
    engine_namespace,
    profile_vector_config,
    select_vector_engine,
)


def _qualified(**overrides):
    values = {
        "compact_ci_green": True,
        "tenant_isolation_equivalent": True,
        "recall_loss_absolute": 0.03,
        "persisted_bytes_ratio_vs_balanced": 0.51,
        "p95_latency_ratio_vs_balanced": 0.95,
        "evidence_ref": "ab-evidence",
    }
    values.update(overrides)
    return EngineQualification(**values)


def test_edge_selects_compact_only_when_all_gates_pass():
    decision = select_vector_engine(OmegaMemoryProfile.EDGE, _qualified())
    assert decision.engine is VectorEngine.COMPACT
    assert decision.qualified is True
    assert decision.fallback_used is False


def test_edge_falls_back_when_recall_gate_fails():
    decision = select_vector_engine(
        OmegaMemoryProfile.EDGE,
        _qualified(recall_loss_absolute=0.051),
    )
    assert decision.engine is VectorEngine.BALANCED
    assert decision.qualified is False
    assert decision.fallback_used is True
    assert any("recall loss" in reason for reason in decision.reasons)


def test_nano_can_accept_recall_loss_that_edge_rejects():
    evidence = _qualified(recall_loss_absolute=0.08, p95_latency_ratio_vs_balanced=1.22)
    nano = select_vector_engine(OmegaMemoryProfile.NANO, evidence)
    edge = select_vector_engine(OmegaMemoryProfile.EDGE, evidence)
    assert nano.engine is VectorEngine.COMPACT
    assert edge.engine is VectorEngine.BALANCED


def test_missing_isolation_evidence_always_falls_back():
    decision = select_vector_engine(
        OmegaMemoryProfile.NANO,
        _qualified(tenant_isolation_equivalent=False),
    )
    assert decision.engine is VectorEngine.BALANCED
    assert decision.fallback_used is True


def test_sovereign_never_auto_selects_compact_in_current_baseline():
    decision = select_vector_engine(OmegaMemoryProfile.SOVEREIGN, _qualified())
    assert decision.engine is VectorEngine.BALANCED
    assert decision.fallback_used is False


def test_engine_namespaces_are_physically_separate():
    compact = select_vector_engine(OmegaMemoryProfile.EDGE, _qualified())
    balanced = select_vector_engine(OmegaMemoryProfile.EDGE, EngineQualification())
    root = Path("/var/lib/pefy/omega-memory")
    assert engine_namespace(root, compact) != engine_namespace(root, balanced)
    assert engine_namespace(root, compact).name == "compact-q8"
    assert engine_namespace(root, balanced).name == "balanced-q8-f16"


def test_profile_configuration_respects_memory_tiers():
    nano = profile_vector_config(OmegaMemoryProfile.NANO, dimensions=384)
    edge = profile_vector_config(OmegaMemoryProfile.EDGE, dimensions=384)
    balanced = profile_vector_config(OmegaMemoryProfile.BALANCED, dimensions=384)
    pro = profile_vector_config(OmegaMemoryProfile.PRO, dimensions=384)

    assert nano.query_memory_budget_mb < edge.query_memory_budget_mb
    assert edge.query_memory_budget_mb < balanced.query_memory_budget_mb
    assert balanced.query_memory_budget_mb < pro.query_memory_budget_mb
    assert nano.max_results < edge.max_results < balanced.max_results < pro.max_results
