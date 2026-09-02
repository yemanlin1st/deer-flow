#!/usr/bin/env python3
"""Run a non-mutating live retrieval qualification against a private RAGFlow lab.

The probe intentionally emits only bounded qualification metadata. Retrieved
chunk text, document names, dataset IDs, endpoint names and API credentials are
not written to the evidence artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from deerflow.pefy_omega.policy import MissionContext
from deerflow.pefy_omega.ragflow_adapter import (
    PefyRagflowMemoryAdapter,
    RagflowConnection,
    RagflowRetrievalPolicy,
    StaticRagflowDatasetResolver,
)


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> int:
    base_url = _required_env("RAGFLOW_LAB_BASE_URL")
    dataset_id = _required_env("RAGFLOW_LAB_DATASET_ID")
    _required_env("RAGFLOW_API_KEY")

    tenant_id = os.environ.get("RAGFLOW_LAB_TENANT_ID", "qualification-tenant").strip()
    project_id = os.environ.get("RAGFLOW_LAB_PROJECT_ID", "qualification-project").strip()
    query = os.environ.get(
        "RAGFLOW_LAB_QUERY", "PEFY RAGFlow qualification retrieval probe"
    ).strip()
    minimum_records = int(os.environ.get("RAGFLOW_LAB_MIN_RECORDS", "1"))
    if minimum_records < 0 or minimum_records > 32:
        raise ValueError("RAGFLOW_LAB_MIN_RECORDS must be between 0 and 32")

    resolver = StaticRagflowDatasetResolver(
        project_datasets={(tenant_id, project_id): (dataset_id,)},
    )
    adapter = PefyRagflowMemoryAdapter(
        connection=RagflowConnection(base_url=base_url),
        dataset_resolver=resolver,
        policy=RagflowRetrievalPolicy(
            max_chunks=8,
            max_chunk_chars=2_000,
            page_size=8,
            similarity_threshold=0.10,
            vector_similarity_weight=0.30,
            top_k=64,
            timeout_seconds=12,
            max_response_bytes=2_000_000,
            max_query_chars=8_000,
            max_datasets=1,
        ),
    )
    mission = MissionContext(
        mission_id="ragflow-live-lab-qualification",
        objective=query,
        tenant_id=tenant_id,
        project_id=project_id,
        confidential=True,
        client_data=False,
    )

    records = tuple(adapter.retrieve(mission=mission, query=query))
    if len(records) < minimum_records:
        raise RuntimeError(
            f"live RAGFlow retrieval returned {len(records)} records; "
            f"minimum required is {minimum_records}"
        )

    for record in records:
        if record.get("tenant_id") != tenant_id:
            raise PermissionError("live qualification tenant scope mismatch")
        if record.get("project_id") != project_id:
            raise PermissionError("live qualification project scope mismatch")
        if record.get("dataset_id") != dataset_id:
            raise PermissionError("live qualification dataset scope mismatch")
        if record.get("validation_state") != "retrieved_unverified":
            raise RuntimeError("live qualification validation-state contract mismatch")

    parsed = urlsplit(base_url)
    evidence = {
        "schema": "pefy.ragflow.live-lab-qualification.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": os.environ.get("GITHUB_SHA"),
        "endpoint_host_digest": _digest(parsed.hostname or ""),
        "dataset_scope_digest": _digest(dataset_id),
        "tenant_scope_digest": _digest(tenant_id),
        "project_scope_digest": _digest(project_id),
        "query_digest": _digest(query),
        "record_count": len(records),
        "minimum_records": minimum_records,
        "https_enforced": parsed.scheme.lower() == "https",
        "tenant_scope_verified": True,
        "project_scope_verified": True,
        "dataset_scope_verified": True,
        "retrieved_content_exported": False,
        "remote_mutation_performed": False,
        "production_claim": False,
        "next_gate": "pinned-image-sbom-vulnerability-resilience-qualification",
    }
    Path("pefy-ragflow-live-lab-qualification.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    )
    print(
        "RAGFlow live lab qualification passed; "
        f"record_count={len(records)}; evidence contains no retrieved content"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
