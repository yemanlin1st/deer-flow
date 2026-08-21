from pathlib import Path

import pytest

from deerflow.pefy_omega.policy import MissionContext, ReleaseClass
from deerflow.pefy_omega.vector_profiles import (
    EngineQualification,
    OmegaMemoryProfile,
    VectorEngine,
    VectorEnginePaths,
    engine_namespace,
    open_profiled_vector_index,
    profile_vector_config,
    scoped_engine_namespace,
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


def test_tenant_project_namespaces_are_hashed_and_physically_separate():
    decision = select_vector_engine(OmegaMemoryProfile.BALANCED, _qualified())
    root = Path("/var/lib/pefy/omega-memory")
    tenant_a = scoped_engine_namespace(
        root,
        decision,
        tenant_id="tenant-alpha-sensitive",
        project_id="project-one-sensitive",
    )
    tenant_b = scoped_engine_namespace(
        root,
        decision,
        tenant_id="tenant-beta-sensitive",
        project_id="project-one-sensitive",
    )
    project_two = scoped_engine_namespace(
        root,
        decision,
        tenant_id="tenant-alpha-sensitive",
        project_id="project-two-sensitive",
    )

    assert tenant_a != tenant_b
    assert tenant_a != project_two
    rendered = str(tenant_a)
    assert "tenant-alpha-sensitive" not in rendered
    assert "project-one-sensitive" not in rendered
    assert "tenant-" in rendered
    assert "project-" in rendered


def test_governed_profile_open_fails_closed_without_tenant_before_loading_library():
    libraries = VectorEnginePaths(
        balanced_library=Path("/missing/balanced.so"),
        compact_library=Path("/missing/compact.so"),
    )
    mission = MissionContext(
        mission_id="missing-tenant",
        objective="restricted retrieval",
        confidential=True,
        release_class=ReleaseClass.RESTRICTED_CLIENT,
    )

    with pytest.raises(PermissionError, match="tenant_id"):
        open_profiled_vector_index(
            profile=OmegaMemoryProfile.SOVEREIGN,
            dimensions=4,
            qualification=None,
            libraries=libraries,
            index_root="/tmp/pefy-vector-test",
            mission=mission,
        )


def test_profile_configuration_respects_memory_tiers():
    nano = profile_vector_config(OmegaMemoryProfile.NANO, dimensions=384)
    edge = profile_vector_config(OmegaMemoryProfile.EDGE, dimensions=384)
    balanced = profile_vector_config(OmegaMemoryProfile.BALANCED, dimensions=384)
    pro = profile_vector_config(OmegaMemoryProfile.PRO, dimensions=384)

    assert nano.query_memory_budget_mb < edge.query_memory_budget_mb
    assert edge.query_memory_budget_mb < balanced.query_memory_budget_mb
    assert balanced.query_memory_budget_mb < pro.query_memory_budget_mb
    assert nano.max_results < edge.max_results < balanced.max_results < pro.max_results
