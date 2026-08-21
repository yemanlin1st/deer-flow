"""Low-memory ΩVECTOR-RS adapter for MƐTAFLOW Ω.

The Rust index stores compact numeric search structures only. Tenant/project
metadata, evidence records and durable source payloads remain authoritative in
OMNIA/RMS/SQLite-compatible stores and are resolved only for the small set of
retrieved IDs.
"""

from __future__ import annotations

import ctypes
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .policy import MissionContext, ReleaseClass


class EmbeddingAdapter(Protocol):
    def embed(self, text: str) -> Sequence[float]: ...


class MetadataResolver(Protocol):
    def fetch(
        self,
        external_ids: Sequence[int],
        *,
        mission: MissionContext,
    ) -> Mapping[int, Mapping[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class RustVectorConfig:
    dimensions: int
    max_neighbors: int = 12
    initial_capacity: int = 4096
    ef_construction: int = 96
    ef_search: int = 80
    rerank_candidates: int = 48
    query_memory_budget_mb: int = 8
    max_results: int = 12
    max_excerpt_chars: int = 1200

    def validate(self) -> None:
        if self.dimensions < 2:
            raise ValueError("dimensions must be >= 2")
        if not 4 <= self.max_neighbors <= 64:
            raise ValueError("max_neighbors must be between 4 and 64")
        if self.ef_construction < self.max_neighbors:
            raise ValueError("ef_construction must be >= max_neighbors")
        if self.query_memory_budget_mb <= 0:
            raise ValueError("query_memory_budget_mb must be > 0")
        if self.max_results <= 0:
            raise ValueError("max_results must be > 0")


@dataclass(frozen=True, slots=True)
class VectorHit:
    external_id: int
    score: float


@dataclass(frozen=True, slots=True)
class VectorStats:
    count: int
    capacity: int
    dimensions: int
    max_neighbors: int
    logical_bytes: int
    mapped_virtual_bytes: int
    approx_bytes_per_vector: int
    query_memory_budget_bytes: int
    generation: int


class _CStats(ctypes.Structure):
    _fields_ = [
        ("count", ctypes.c_uint32),
        ("capacity", ctypes.c_uint32),
        ("dimensions", ctypes.c_uint32),
        ("max_neighbors", ctypes.c_uint32),
        ("logical_bytes", ctypes.c_uint64),
        ("mapped_virtual_bytes", ctypes.c_uint64),
        ("approx_bytes_per_vector", ctypes.c_uint64),
        ("query_memory_budget_bytes", ctypes.c_uint64),
        ("generation", ctypes.c_uint64),
    ]


class RustVectorIndex:
    """ctypes binding that avoids a resident Python copy of the vector corpus."""

    def __init__(
        self,
        *,
        library_path: str | Path,
        index_path: str | Path,
        config: RustVectorConfig,
    ) -> None:
        config.validate()
        self._config = config
        self._lib = ctypes.CDLL(str(Path(library_path)))
        self._configure_abi()
        encoded_path = str(Path(index_path)).encode("utf-8")
        self._handle = self._lib.pefy_vector_open(
            encoded_path,
            config.dimensions,
            config.max_neighbors,
            config.initial_capacity,
            config.ef_construction,
            config.ef_search,
            config.rerank_candidates,
            config.query_memory_budget_mb,
        )
        if not self._handle:
            raise RuntimeError(self._last_error() or "ΩVECTOR-RS failed to open")
        self._closed = False

    def _configure_abi(self) -> None:
        lib = self._lib
        lib.pefy_vector_open.argtypes = [
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        lib.pefy_vector_open.restype = ctypes.c_void_p
        lib.pefy_vector_add.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        lib.pefy_vector_add.restype = ctypes.c_int32
        lib.pefy_vector_search.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_size_t,
        ]
        lib.pefy_vector_search.restype = ctypes.c_ssize_t
        lib.pefy_vector_mark_deleted.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.pefy_vector_mark_deleted.restype = ctypes.c_int32
        lib.pefy_vector_flush.argtypes = [ctypes.c_void_p]
        lib.pefy_vector_flush.restype = ctypes.c_int32
        lib.pefy_vector_stats.argtypes = [ctypes.c_void_p, ctypes.POINTER(_CStats)]
        lib.pefy_vector_stats.restype = ctypes.c_int32
        lib.pefy_vector_last_error.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        lib.pefy_vector_last_error.restype = ctypes.c_size_t
        lib.pefy_vector_close.argtypes = [ctypes.c_void_p]
        lib.pefy_vector_close.restype = None

    def _last_error(self) -> str:
        required = int(self._lib.pefy_vector_last_error(None, 0))
        if required <= 1:
            return ""
        buffer = ctypes.create_string_buffer(required)
        self._lib.pefy_vector_last_error(buffer, required)
        return buffer.value.decode("utf-8", errors="replace")

    def _vector_array(self, vector: Sequence[float]) -> Any:
        if len(vector) != self._config.dimensions:
            raise ValueError(
                f"vector dimension mismatch: expected {self._config.dimensions}, got {len(vector)}"
            )
        array_type = ctypes.c_float * self._config.dimensions
        return array_type(*(float(value) for value in vector))

    def add(self, external_id: int, vector: Sequence[float]) -> int:
        self._ensure_open()
        values = self._vector_array(vector)
        node = ctypes.c_uint32()
        status = int(
            self._lib.pefy_vector_add(
                self._handle,
                ctypes.c_uint64(external_id),
                values,
                len(vector),
                ctypes.byref(node),
            )
        )
        if status != 0:
            raise RuntimeError(self._last_error() or f"ΩVECTOR-RS add failed ({status})")
        return int(node.value)

    def search(self, vector: Sequence[float], k: int) -> tuple[VectorHit, ...]:
        self._ensure_open()
        if k <= 0:
            return ()
        values = self._vector_array(vector)
        ids_type = ctypes.c_uint64 * k
        scores_type = ctypes.c_float * k
        ids = ids_type()
        scores = scores_type()
        count = int(
            self._lib.pefy_vector_search(
                self._handle,
                values,
                len(vector),
                k,
                ids,
                scores,
                k,
            )
        )
        if count < 0:
            raise RuntimeError(self._last_error() or f"ΩVECTOR-RS search failed ({count})")
        return tuple(VectorHit(int(ids[i]), float(scores[i])) for i in range(count))

    def mark_deleted(self, node: int) -> None:
        self._ensure_open()
        status = int(self._lib.pefy_vector_mark_deleted(self._handle, int(node)))
        if status != 0:
            raise RuntimeError(self._last_error() or f"ΩVECTOR-RS delete failed ({status})")

    def flush(self) -> None:
        self._ensure_open()
        status = int(self._lib.pefy_vector_flush(self._handle))
        if status != 0:
            raise RuntimeError(self._last_error() or f"ΩVECTOR-RS flush failed ({status})")

    def stats(self) -> VectorStats:
        self._ensure_open()
        raw = _CStats()
        status = int(self._lib.pefy_vector_stats(self._handle, ctypes.byref(raw)))
        if status != 0:
            raise RuntimeError(self._last_error() or f"ΩVECTOR-RS stats failed ({status})")
        return VectorStats(
            count=int(raw.count),
            capacity=int(raw.capacity),
            dimensions=int(raw.dimensions),
            max_neighbors=int(raw.max_neighbors),
            logical_bytes=int(raw.logical_bytes),
            mapped_virtual_bytes=int(raw.mapped_virtual_bytes),
            approx_bytes_per_vector=int(raw.approx_bytes_per_vector),
            query_memory_budget_bytes=int(raw.query_memory_budget_bytes),
            generation=int(raw.generation),
        )

    def close(self) -> None:
        if not self._closed and self._handle:
            self._lib.pefy_vector_close(self._handle)
            self._closed = True
            self._handle = None

    def _ensure_open(self) -> None:
        if self._closed or not self._handle:
            raise RuntimeError("ΩVECTOR-RS index is closed")

    def __enter__(self) -> RustVectorIndex:
        self._ensure_open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class OmegaVectorMemoryAdapter:
    """Tenant/project-scoped retrieval adapter returning compact evidence handles.

    The embedding model is replaceable. The vector index never becomes the
    authoritative record: metadata is resolved from the governed durable store
    only after the Rust index selects a small candidate set.
    """

    _ALLOWED_FIELDS = (
        "kind",
        "summary",
        "excerpt",
        "evidence_ref",
        "source_ref",
        "updated_at",
        "project_id",
        "tenant_id",
    )

    def __init__(
        self,
        *,
        index: RustVectorIndex,
        embedder: EmbeddingAdapter,
        metadata: MetadataResolver,
        config: RustVectorConfig,
    ) -> None:
        self._index = index
        self._embedder = embedder
        self._metadata = metadata
        self._config = config

    @staticmethod
    def _tenant_context_required(mission: MissionContext) -> bool:
        return bool(
            mission.confidential
            or mission.client_data
            or mission.release_class
            in {ReleaseClass.INTERNAL_CONFIDENTIAL, ReleaseClass.RESTRICTED_CLIENT}
        )

    @classmethod
    def _assert_mission_scope(cls, mission: MissionContext) -> None:
        if cls._tenant_context_required(mission) and not (mission.tenant_id or "").strip():
            raise PermissionError(
                "tenant_id is required before confidential, restricted or client-scoped vector retrieval"
            )

    @staticmethod
    def _assert_record_scope(record: Mapping[str, Any], mission: MissionContext) -> None:
        if mission.tenant_id:
            record_tenant = record.get("tenant_id")
            if record_tenant is None:
                raise PermissionError("retrieved metadata is missing required tenant_id")
            if str(record_tenant) != mission.tenant_id:
                raise PermissionError("retrieved metadata tenant_id does not match mission tenant")

        if mission.project_id:
            record_project = record.get("project_id")
            if record_project is None:
                raise PermissionError("retrieved metadata is missing required project_id")
            if str(record_project) != mission.project_id:
                raise PermissionError("retrieved metadata project_id does not match mission project")

    def retrieve(self, *, mission: MissionContext, query: str) -> Sequence[Mapping[str, Any]]:
        self._assert_mission_scope(mission)
        query_vector = self._embedder.embed(query)
        hits = self._index.search(query_vector, self._config.max_results)
        if not hits:
            return ()
        ids = tuple(hit.external_id for hit in hits)
        records = self._metadata.fetch(ids, mission=mission)
        output: list[Mapping[str, Any]] = []
        for hit in hits:
            record = records.get(hit.external_id)
            if record is None:
                continue
            self._assert_record_scope(record, mission)
            compact: dict[str, Any] = {
                "memory_id": hit.external_id,
                "score": hit.score,
            }
            for field in self._ALLOWED_FIELDS:
                if field not in record:
                    continue
                value = record[field]
                if field in {"summary", "excerpt"} and isinstance(value, str):
                    value = value[: self._config.max_excerpt_chars]
                compact[field] = value
            output.append(compact)
        return tuple(output)
