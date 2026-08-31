from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from deerflow.pefy_omega.policy import MissionContext
from deerflow.pefy_omega.ragflow_adapter import (
    PefyRagflowMemoryAdapter,
    RagflowConnection,
    RagflowRetrievalPolicy,
    StaticRagflowDatasetResolver,
)


def _mission(*, tenant: str | None = "tenant-a", project: str | None = "project-a") -> MissionContext:
    return MissionContext(
        mission_id="mission-1",
        objective="find governed context",
        tenant_id=tenant,
        project_id=project,
    )


def _adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: Mapping[str, Any],
    resolver: StaticRagflowDatasetResolver | None = None,
    policy: RagflowRetrievalPolicy | None = None,
    captured: dict[str, Any] | None = None,
) -> PefyRagflowMemoryAdapter:
    monkeypatch.setenv("RAGFLOW_API_KEY", "test-only-secret")

    def transport(
        endpoint: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        if captured is not None:
            captured.update(
                endpoint=endpoint,
                headers=dict(headers),
                payload=dict(payload),
                timeout_seconds=timeout_seconds,
            )
        return response

    return PefyRagflowMemoryAdapter(
        connection=RagflowConnection(base_url="https://ragflow.internal"),
        dataset_resolver=resolver
        or StaticRagflowDatasetResolver(
            project_datasets={("tenant-a", "project-a"): ("dataset-project-a",)}
        ),
        policy=policy,
        transport=transport,
    )


def test_connection_requires_https_and_rejects_embedded_url_state() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        RagflowConnection(base_url="http://ragflow.internal").endpoint()
    with pytest.raises(ValueError, match="credentials"):
        RagflowConnection(base_url="https://user:pass@ragflow.internal").endpoint()
    with pytest.raises(ValueError, match="query or fragment"):
        RagflowConnection(base_url="https://ragflow.internal?x=1").endpoint()


def test_requires_tenant_before_external_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter(monkeypatch, response={"code": 0, "data": {"chunks": []}})

    with pytest.raises(PermissionError, match="tenant_id"):
        adapter.retrieve(mission=_mission(tenant=None, project=None), query="context")


def test_project_dataset_is_resolved_locally_and_sent_to_ragflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    adapter = _adapter(
        monkeypatch,
        captured=captured,
        response={
            "code": 0,
            "data": {
                "chunks": [
                    {
                        "id": "chunk-1",
                        "dataset_id": "dataset-project-a",
                        "document_id": "doc-1",
                        "document_keyword": "Policy.pdf",
                        "content": "approved context",
                        "similarity": 0.91,
                    }
                ]
            },
        },
    )

    records = adapter.retrieve(mission=_mission(), query="governed question")

    assert captured["payload"]["dataset_ids"] == ["dataset-project-a"]
    assert captured["payload"]["question"] == "governed question"
    assert records[0]["tenant_id"] == "tenant-a"
    assert records[0]["project_id"] == "project-a"
    assert records[0]["dataset_id"] == "dataset-project-a"
    assert records[0]["validation_state"] == "retrieved_unverified"


def test_project_scope_does_not_fall_back_to_tenant_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    resolver = StaticRagflowDatasetResolver(
        tenant_datasets={"tenant-a": ("dataset-tenant-a",)}
    )
    adapter = _adapter(
        monkeypatch,
        response={"code": 0, "data": {"chunks": []}},
        resolver=resolver,
        captured=captured,
    )

    records = adapter.retrieve(mission=_mission(), query="context")

    assert records == ()
    assert captured == {}


def test_unexpected_dataset_in_response_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter(
        monkeypatch,
        response={
            "code": 0,
            "data": {
                "chunks": [
                    {
                        "id": "chunk-x",
                        "dataset_id": "dataset-other-tenant",
                        "content": "must never hydrate",
                    }
                ]
            },
        },
    )

    with pytest.raises(PermissionError, match="authorized dataset"):
        adapter.retrieve(mission=_mission(), query="context")


def test_context_is_bounded_and_vectors_or_arbitrary_metadata_are_not_hydrated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = RagflowRetrievalPolicy(max_chunks=2, max_chunk_chars=10)
    adapter = _adapter(
        monkeypatch,
        policy=policy,
        response={
            "code": 0,
            "data": {
                "chunks": [
                    {
                        "id": "chunk-1",
                        "dataset_id": "dataset-project-a",
                        "content": "1234567890EXCESS",
                        "q_1024_vec": [0.1, 0.2],
                        "sensitive_untrusted_metadata": "drop-me",
                    },
                    {
                        "id": "chunk-2",
                        "dataset_id": "dataset-project-a",
                        "content": "abcdefghijEXCESS",
                    },
                    {
                        "id": "chunk-3",
                        "dataset_id": "dataset-project-a",
                        "content": "not-reached",
                    },
                ]
            },
        },
    )

    records = adapter.retrieve(mission=_mission(), query="context")

    assert len(records) == 2
    assert records[0]["content"] == "1234567890"
    assert records[1]["content"] == "abcdefghij"
    assert "q_1024_vec" not in records[0]
    assert "sensitive_untrusted_metadata" not in records[0]


def test_ragflow_application_error_is_not_silently_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(
        monkeypatch,
        response={"code": 100, "message": "invalid dataset", "data": None},
    )

    with pytest.raises(RuntimeError, match="invalid dataset"):
        adapter.retrieve(mission=_mission(), query="context")
