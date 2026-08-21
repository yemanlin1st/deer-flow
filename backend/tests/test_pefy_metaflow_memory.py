from __future__ import annotations

from dataclasses import dataclass

from deerflow.pefy_omega.memory_budget import (
    MemoryBudgetPolicy,
    approximate_context_chars,
    compact_memory_records,
)
from deerflow.pefy_omega.orchestrator import PefyMetaFlowOrchestrator
from deerflow.pefy_omega.policy import MissionContext
from deerflow.pefy_omega.rust_vector import (
    OmegaVectorMemoryAdapter,
    RustVectorConfig,
    VectorHit,
)


@dataclass
class _FakeIndex:
    hits: tuple[VectorHit, ...]

    def search(self, vector, k):
        assert k > 0
        return self.hits[:k]


class _FakeEmbedder:
    def embed(self, text: str):
        assert text
        return [1.0, 0.0, 0.0, 0.0]


class _FakeMetadata:
    def fetch(self, external_ids, *, mission):
        assert mission.mission_id == "memory-test"
        return {
            101: {
                "kind": "evidence",
                "summary": "short summary",
                "excerpt": "x" * 500,
                "evidence_ref": "ev-101",
                "tenant_id": "tenant-a",
                "secret_blob": "SHOULD-NOT-BE-HYDRATED" * 10_000,
            },
            202: {
                "kind": "decision",
                "summary": "decision summary",
                "evidence_ref": "ev-202",
                "tenant_id": "tenant-a",
            },
        }


class _UnboundedMemory:
    def retrieve(self, *, mission, query):
        assert mission.mission_id == "bounded-memory-test"
        assert query
        return (
            {
                "evidence_ref": "same-evidence",
                "summary": "a" * 5_000,
                "raw_payload": "b" * 50_000,
                "embedding": [0.1] * 20_000,
                "tenant_id": "tenant-a",
            },
            {
                "evidence_ref": "same-evidence",
                "summary": "duplicate must be removed",
                "tenant_id": "tenant-a",
            },
            {
                "evidence_ref": "second-evidence",
                "summary": "c" * 5_000,
                "tenant_id": "tenant-a",
            },
        )


def test_memory_adapter_hydrates_only_compact_allowlisted_fields():
    config = RustVectorConfig(
        dimensions=4,
        max_neighbors=4,
        max_results=2,
        max_excerpt_chars=64,
    )
    adapter = OmegaVectorMemoryAdapter(
        index=_FakeIndex((VectorHit(101, 0.98), VectorHit(202, 0.85))),
        embedder=_FakeEmbedder(),
        metadata=_FakeMetadata(),
        config=config,
    )
    mission = MissionContext(mission_id="memory-test", objective="retrieve evidence")

    records = adapter.retrieve(mission=mission, query="important prior evidence")

    assert len(records) == 2
    first = records[0]
    assert first["memory_id"] == 101
    assert first["evidence_ref"] == "ev-101"
    assert len(first["excerpt"]) == 64
    assert "secret_blob" not in first
    assert set(first).issubset(
        {
            "memory_id",
            "score",
            "kind",
            "summary",
            "excerpt",
            "evidence_ref",
            "source_ref",
            "updated_at",
            "project_id",
            "tenant_id",
        }
    )


def test_rust_vector_config_rejects_unbounded_or_invalid_memory_settings():
    try:
        RustVectorConfig(dimensions=4, query_memory_budget_mb=0).validate()
    except ValueError as error:
        assert "query_memory_budget_mb" in str(error)
    else:
        raise AssertionError("zero query memory budget must be rejected")

    try:
        RustVectorConfig(dimensions=4, max_neighbors=3).validate()
    except ValueError as error:
        assert "max_neighbors" in str(error)
    else:
        raise AssertionError("undersized graph configuration must be rejected")


def test_generic_memory_budget_deduplicates_and_excludes_heavy_fields():
    policy = MemoryBudgetPolicy(
        max_records=2,
        max_total_chars=80,
        max_string_chars=40,
        max_scalar_fields=8,
    )
    records = compact_memory_records(
        _UnboundedMemory().retrieve(
            mission=MissionContext(
                mission_id="bounded-memory-test",
                objective="retrieve compact context",
            ),
            query="compact context",
        ),
        policy,
    )

    assert len(records) == 2
    assert records[0]["evidence_ref"] == "same-evidence"
    assert records[1]["evidence_ref"] == "second-evidence"
    assert all("raw_payload" not in record for record in records)
    assert all("embedding" not in record for record in records)
    assert approximate_context_chars(records) <= 80


def test_orchestrator_enforces_memory_budget_for_any_backend():
    policy = MemoryBudgetPolicy(
        max_records=1,
        max_total_chars=60,
        max_string_chars=30,
        max_scalar_fields=8,
    )
    orchestrator = PefyMetaFlowOrchestrator(
        memory_adapter=_UnboundedMemory(),
        memory_budget_policy=policy,
    )
    prepared = orchestrator.prepare_mission(
        MissionContext(
            mission_id="bounded-memory-test",
            objective="retrieve compact context",
        )
    )

    assert len(prepared.prior_context) == 1
    assert approximate_context_chars(prepared.prior_context) <= 60
    assert "raw_payload" not in prepared.prior_context[0]
    assert "embedding" not in prepared.prior_context[0]
    assert prepared.execution_packet["constraints"]["bounded_memory_context"] is True
    assert prepared.execution_packet["acceptance"]["memory_budget_gate"] is True
