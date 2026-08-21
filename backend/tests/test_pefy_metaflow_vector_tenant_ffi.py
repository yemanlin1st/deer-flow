from __future__ import annotations

import os
from pathlib import Path

import pytest

from deerflow.pefy_omega.policy import MissionContext, ReleaseClass
from deerflow.pefy_omega.rust_vector import (
    OmegaVectorMemoryAdapter,
    RustVectorConfig,
    RustVectorIndex,
)
from deerflow.pefy_omega.vector_profiles import (
    OmegaMemoryProfile,
    VectorEngine,
    VectorEngineDecision,
    scoped_engine_namespace,
)


class _StaticEmbedder:
    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    def embed(self, text: str) -> list[float]:
        assert text
        return list(self._vector)


class _ScopedMetadata:
    def __init__(self, records: dict[tuple[str, str, int], dict[str, object]]) -> None:
        self._records = records

    def fetch(self, external_ids, *, mission):
        assert mission.tenant_id
        assert mission.project_id
        output = {}
        for external_id in external_ids:
            record = self._records.get((mission.tenant_id, mission.project_id, int(external_id)))
            if record is not None:
                output[int(external_id)] = record
        return output


class _CrossTenantMetadata:
    def fetch(self, external_ids, *, mission):
        assert mission.tenant_id == "tenant-alpha"
        return {
            int(external_id): {
                "kind": "evidence",
                "summary": "must never cross tenant boundary",
                "evidence_ref": f"evil-{external_id}",
                "tenant_id": "tenant-beta",
                "project_id": mission.project_id,
            }
            for external_id in external_ids
        }


class _CrossProjectMetadata:
    def fetch(self, external_ids, *, mission):
        assert mission.tenant_id == "tenant-alpha"
        return {
            int(external_id): {
                "kind": "evidence",
                "summary": "must never cross project boundary",
                "evidence_ref": f"wrong-project-{external_id}",
                "tenant_id": mission.tenant_id,
                "project_id": "project-other",
            }
            for external_id in external_ids
        }


def _library_path(env_name: str) -> Path:
    value = os.environ.get(env_name)
    if not value:
        pytest.fail(f"{env_name} must point to the built Rust cdylib")
    path = Path(value)
    assert path.is_file(), f"Rust cdylib not found: {path}"
    return path


def _decision(engine: VectorEngine) -> VectorEngineDecision:
    profile = OmegaMemoryProfile.EDGE if engine is VectorEngine.COMPACT else OmegaMemoryProfile.BALANCED
    return VectorEngineDecision(
        profile=profile,
        engine=engine,
        qualified=True,
        fallback_used=False,
        reasons=("tenant isolation FFI qualification",),
        evidence_ref="tenant-ffi",
    )


def _config() -> RustVectorConfig:
    return RustVectorConfig(
        dimensions=4,
        max_neighbors=4,
        initial_capacity=4,
        ef_construction=16,
        ef_search=16,
        rerank_candidates=4,
        query_memory_budget_mb=1,
        max_results=2,
        max_excerpt_chars=96,
    )


@pytest.mark.parametrize(
    ("engine", "library_env"),
    (
        (VectorEngine.BALANCED, "PEFY_VECTOR_BALANCED_LIB"),
        (VectorEngine.COMPACT, "PEFY_VECTOR_COMPACT_LIB"),
    ),
)
def test_real_rust_ffi_enforces_tenant_project_isolation(
    tmp_path: Path,
    engine: VectorEngine,
    library_env: str,
) -> None:
    library = _library_path(library_env)
    decision = _decision(engine)
    config = _config()
    root = tmp_path / engine.value.lower()

    tenant_a_path = scoped_engine_namespace(
        root,
        decision,
        tenant_id="tenant-alpha",
        project_id="project-one",
    )
    tenant_b_path = scoped_engine_namespace(
        root,
        decision,
        tenant_id="tenant-beta",
        project_id="project-one",
    )

    assert tenant_a_path != tenant_b_path
    assert "tenant-alpha" not in str(tenant_a_path)
    assert "tenant-beta" not in str(tenant_b_path)
    assert "project-one" not in str(tenant_a_path)

    same_external_id = 4242
    with (
        RustVectorIndex(
            library_path=library,
            index_path=tenant_a_path,
            config=config,
        ) as tenant_a_index,
        RustVectorIndex(
            library_path=library,
            index_path=tenant_b_path,
            config=config,
        ) as tenant_b_index,
    ):
        tenant_a_index.add(same_external_id, [1.0, 0.0, 0.0, 0.0])
        tenant_a_index.add(5001, [0.8, 0.2, 0.0, 0.0])
        tenant_b_index.add(same_external_id, [0.0, 1.0, 0.0, 0.0])
        tenant_b_index.add(6001, [0.2, 0.8, 0.0, 0.0])
        tenant_a_index.flush()
        tenant_b_index.flush()

        assert tenant_a_index.stats().count == 2
        assert tenant_b_index.stats().count == 2
        assert tenant_a_index.search([1.0, 0.0, 0.0, 0.0], 1)[0].external_id == same_external_id
        assert tenant_b_index.search([0.0, 1.0, 0.0, 0.0], 1)[0].external_id == same_external_id

        mission_a = MissionContext(
            mission_id=f"ffi-{engine.value}-tenant-a",
            objective="retrieve tenant alpha evidence",
            tenant_id="tenant-alpha",
            project_id="project-one",
            confidential=True,
            client_data=True,
            release_class=ReleaseClass.RESTRICTED_CLIENT,
        )
        mission_b = MissionContext(
            mission_id=f"ffi-{engine.value}-tenant-b",
            objective="retrieve tenant beta evidence",
            tenant_id="tenant-beta",
            project_id="project-one",
            confidential=True,
            client_data=True,
            release_class=ReleaseClass.RESTRICTED_CLIENT,
        )

        records = {
            ("tenant-alpha", "project-one", same_external_id): {
                "kind": "evidence",
                "summary": "alpha evidence",
                "evidence_ref": "alpha-4242",
                "tenant_id": "tenant-alpha",
                "project_id": "project-one",
            },
            ("tenant-alpha", "project-one", 5001): {
                "kind": "evidence",
                "summary": "alpha secondary",
                "evidence_ref": "alpha-5001",
                "tenant_id": "tenant-alpha",
                "project_id": "project-one",
            },
            ("tenant-beta", "project-one", same_external_id): {
                "kind": "evidence",
                "summary": "beta evidence",
                "evidence_ref": "beta-4242",
                "tenant_id": "tenant-beta",
                "project_id": "project-one",
            },
            ("tenant-beta", "project-one", 6001): {
                "kind": "evidence",
                "summary": "beta secondary",
                "evidence_ref": "beta-6001",
                "tenant_id": "tenant-beta",
                "project_id": "project-one",
            },
        }

        alpha_adapter = OmegaVectorMemoryAdapter(
            index=tenant_a_index,
            embedder=_StaticEmbedder([1.0, 0.0, 0.0, 0.0]),
            metadata=_ScopedMetadata(records),
            config=config,
        )
        beta_adapter = OmegaVectorMemoryAdapter(
            index=tenant_b_index,
            embedder=_StaticEmbedder([0.0, 1.0, 0.0, 0.0]),
            metadata=_ScopedMetadata(records),
            config=config,
        )

        alpha_results = alpha_adapter.retrieve(mission=mission_a, query=mission_a.objective)
        beta_results = beta_adapter.retrieve(mission=mission_b, query=mission_b.objective)
        assert alpha_results[0]["memory_id"] == same_external_id
        assert alpha_results[0]["summary"] == "alpha evidence"
        assert alpha_results[0]["tenant_id"] == "tenant-alpha"
        assert beta_results[0]["memory_id"] == same_external_id
        assert beta_results[0]["summary"] == "beta evidence"
        assert beta_results[0]["tenant_id"] == "tenant-beta"

        cross_tenant_adapter = OmegaVectorMemoryAdapter(
            index=tenant_a_index,
            embedder=_StaticEmbedder([1.0, 0.0, 0.0, 0.0]),
            metadata=_CrossTenantMetadata(),
            config=config,
        )
        with pytest.raises(PermissionError, match="tenant_id does not match"):
            cross_tenant_adapter.retrieve(mission=mission_a, query=mission_a.objective)

        cross_project_adapter = OmegaVectorMemoryAdapter(
            index=tenant_a_index,
            embedder=_StaticEmbedder([1.0, 0.0, 0.0, 0.0]),
            metadata=_CrossProjectMetadata(),
            config=config,
        )
        with pytest.raises(PermissionError, match="project_id does not match"):
            cross_project_adapter.retrieve(mission=mission_a, query=mission_a.objective)

        missing_tenant = MissionContext(
            mission_id="ffi-missing-tenant",
            objective="restricted retrieval without tenant",
            confidential=True,
            release_class=ReleaseClass.RESTRICTED_CLIENT,
        )
        with pytest.raises(PermissionError, match="tenant_id is required"):
            alpha_adapter.retrieve(mission=missing_tenant, query=missing_tenant.objective)

    assert tenant_a_path.is_dir()
    assert tenant_b_path.is_dir()
    assert tenant_a_path != tenant_b_path
