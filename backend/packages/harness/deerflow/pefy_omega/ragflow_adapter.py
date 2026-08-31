"""Fail-closed RAGFlow retrieval adapter for PEFY MƐTAFLOW Ω.

RAGFlow is treated as a replaceable retrieval/ingestion subsystem, never as
the authorization authority. Tenant/project access is resolved locally before
any request, then re-checked against every returned chunk before hydration.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .policy import MissionContext

RagflowTransport = Callable[
    [str, Mapping[str, str], Mapping[str, Any], float],
    Mapping[str, Any],
]


@dataclass(frozen=True, slots=True)
class RagflowConnection:
    """Connection metadata without embedding secret values in code/config."""

    base_url: str
    api_key_env: str = "RAGFLOW_API_KEY"
    retrieval_path: str = "/api/v1/retrieval"

    def endpoint(self) -> str:
        base = self.base_url.strip().rstrip("/")
        if not base:
            raise ValueError("RAGFlow base_url must not be empty")

        parsed = urlsplit(base)
        if parsed.scheme.lower() != "https":
            raise ValueError("RAGFlow base_url must use HTTPS")
        if not parsed.hostname:
            raise ValueError("RAGFlow base_url must include a hostname")
        if parsed.username or parsed.password:
            raise ValueError("RAGFlow base_url must not embed credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("RAGFlow base_url must not include query or fragment components")

        path = self.retrieval_path.strip()
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{base}{path}"


@dataclass(frozen=True, slots=True)
class RagflowRetrievalPolicy:
    """Bounded retrieval policy applied before context reaches MƐTAFLOW Ω."""

    max_chunks: int = 8
    max_chunk_chars: int = 4_000
    page_size: int = 12
    similarity_threshold: float = 0.20
    vector_similarity_weight: float = 0.30
    top_k: int = 64
    timeout_seconds: float = 12.0
    require_tenant: bool = True
    allow_tenant_fallback_for_project: bool = False

    def validate(self) -> None:
        if self.max_chunks <= 0:
            raise ValueError("max_chunks must be positive")
        if self.max_chunk_chars <= 0:
            raise ValueError("max_chunk_chars must be positive")
        if self.page_size <= 0:
            raise ValueError("page_size must be positive")
        if not 0 <= self.similarity_threshold <= 1:
            raise ValueError("similarity_threshold must be between 0 and 1")
        if not 0 <= self.vector_similarity_weight <= 1:
            raise ValueError("vector_similarity_weight must be between 0 and 1")
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class StaticRagflowDatasetResolver:
    """Resolve pre-authorized RAGFlow datasets from local mission scope.

    Dataset identifiers are never accepted from the mission objective or model
    output. Project mappings are strict by default; a project-scoped mission
    does not silently widen to tenant-wide data unless policy explicitly opts in.
    """

    tenant_datasets: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    project_datasets: Mapping[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)
    allow_tenant_fallback_for_project: bool = False

    @staticmethod
    def _clean(values: Sequence[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(v.strip() for v in values if v and v.strip()))

    def resolve(self, mission: MissionContext) -> tuple[str, ...]:
        tenant_id = (mission.tenant_id or "").strip()
        project_id = (mission.project_id or "").strip()
        if not tenant_id:
            return ()

        if project_id:
            scoped = self._clean(self.project_datasets.get((tenant_id, project_id), ()))
            if scoped:
                return scoped
            if not self.allow_tenant_fallback_for_project:
                return ()

        return self._clean(self.tenant_datasets.get(tenant_id, ()))


def _default_transport(
    endpoint: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    request = Request(
        endpoint,
        data=json.dumps(dict(payload)).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
            raw = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("RAGFlow retrieval transport failed") from exc

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("RAGFlow returned an invalid JSON response") from exc
    if not isinstance(parsed, Mapping):
        raise RuntimeError("RAGFlow returned a non-object JSON response")
    return parsed


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class PefyRagflowMemoryAdapter:
    """RAGFlow-backed implementation of the MƐTAFLOW Ω MemoryAdapter protocol."""

    def __init__(
        self,
        *,
        connection: RagflowConnection,
        dataset_resolver: StaticRagflowDatasetResolver,
        policy: RagflowRetrievalPolicy | None = None,
        transport: RagflowTransport | None = None,
    ) -> None:
        self._connection = connection
        self._resolver = dataset_resolver
        self._policy = policy or RagflowRetrievalPolicy(
            allow_tenant_fallback_for_project=dataset_resolver.allow_tenant_fallback_for_project
        )
        self._policy.validate()
        self._transport = transport or _default_transport

    def _headers(self) -> Mapping[str, str]:
        api_key = os.environ.get(self._connection.api_key_env, "").strip()
        if not api_key:
            raise RuntimeError(
                f"RAGFlow API key is missing from environment variable {self._connection.api_key_env}"
            )
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def retrieve(self, *, mission: MissionContext, query: str) -> Sequence[Mapping[str, Any]]:
        tenant_id = (mission.tenant_id or "").strip()
        project_id = (mission.project_id or "").strip() or None
        if self._policy.require_tenant and not tenant_id:
            raise PermissionError("tenant_id is required for RAGFlow retrieval")

        dataset_ids = self._resolver.resolve(mission)
        if not dataset_ids:
            return ()

        question = query.strip()
        if not question:
            return ()

        payload: dict[str, Any] = {
            "question": question,
            "dataset_ids": list(dataset_ids),
            "page": 1,
            "page_size": max(self._policy.page_size, self._policy.max_chunks),
            "similarity_threshold": self._policy.similarity_threshold,
            "vector_similarity_weight": self._policy.vector_similarity_weight,
            "top_k": self._policy.top_k,
            "keyword": False,
            "highlight": False,
        }
        response = self._transport(
            self._connection.endpoint(),
            self._headers(),
            payload,
            self._policy.timeout_seconds,
        )

        if response.get("code") != 0:
            message = str(response.get("message") or "retrieval failed")[:240]
            raise RuntimeError(f"RAGFlow retrieval rejected: {message}")

        data = response.get("data") or {}
        if not isinstance(data, Mapping):
            raise RuntimeError("RAGFlow response data is not an object")
        chunks = data.get("chunks") or ()
        if not isinstance(chunks, Sequence) or isinstance(chunks, (str, bytes, bytearray)):
            raise RuntimeError("RAGFlow response chunks are not a sequence")

        allowed_datasets = frozenset(dataset_ids)
        records: list[Mapping[str, Any]] = []
        for chunk in chunks:
            if len(records) >= self._policy.max_chunks:
                break
            if not isinstance(chunk, Mapping):
                continue

            returned_dataset = str(chunk.get("dataset_id") or "").strip()
            if returned_dataset not in allowed_datasets:
                raise PermissionError(
                    "RAGFlow returned a chunk outside the locally authorized dataset scope"
                )

            content = str(chunk.get("content") or chunk.get("content_with_weight") or "").strip()
            if not content:
                continue
            content = content[: self._policy.max_chunk_chars]

            records.append(
                {
                    "memory_id": str(chunk.get("id") or ""),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "classification": "retrieved_external_context",
                    "source_type": "ragflow",
                    "relevance_score": _number(chunk.get("similarity")),
                    "validation_state": "retrieved_unverified",
                    "dataset_id": returned_dataset,
                    "document_id": str(chunk.get("document_id") or ""),
                    "document_name": str(chunk.get("document_keyword") or "")[:512],
                    "content": content,
                }
            )

        return tuple(records)
