"""PEFY MƐTAFLOW Ω sovereign orchestration overlay.

This package contains PEFY-owned integration logic that can sit above a
replaceable agent-harness runtime. It deliberately avoids embedding secrets,
client data, or private prompts in the public upstream-compatible codebase.
"""

from .export_filter import (
    ExportableMessage,
    ExportedMessage,
    ExportVisibility,
    filter_export_messages,
    render_export_text,
)
from .humanize import OutputHygienePolicy, clean_output
from .memory_budget import (
    MemoryBudgetPolicy,
    approximate_context_chars,
    compact_memory_records,
)
from .orchestrator import PefyMetaFlowOrchestrator
from .policy import (
    ALL_CHALLENGE_FUNCTIONS,
    ALL_COUNCILS,
    ALL_COUNSELLORS,
    MissionContext,
    Mode,
    ReleaseClass,
    RouteDecision,
    route_mission,
)
from .ragflow_adapter import (
    PefyRagflowMemoryAdapter,
    RagflowConnection,
    RagflowRetrievalPolicy,
    StaticRagflowDatasetResolver,
)
from .registry import (
    METAFLOW_AGENCY,
    METAFLOW_AGENT,
    AgencyDefinition,
    AgentDefinition,
    select_execution_agencies,
)
from .rust_vector import (
    EmbeddingAdapter,
    MetadataResolver,
    OmegaVectorMemoryAdapter,
    RustVectorConfig,
    RustVectorIndex,
    VectorHit,
    VectorStats,
)
from .scheduler import (
    ExecutionWave,
    TaskNode,
    build_execution_waves,
    burst_smoothing_offsets,
    recommended_parallelism,
)

__all__ = [
    "ALL_CHALLENGE_FUNCTIONS",
    "ALL_COUNCILS",
    "ALL_COUNSELLORS",
    "AgencyDefinition",
    "AgentDefinition",
    "EmbeddingAdapter",
    "ExecutionWave",
    "ExportableMessage",
    "ExportedMessage",
    "ExportVisibility",
    "METAFLOW_AGENCY",
    "METAFLOW_AGENT",
    "MemoryBudgetPolicy",
    "MetadataResolver",
    "MissionContext",
    "Mode",
    "OmegaVectorMemoryAdapter",
    "OutputHygienePolicy",
    "PefyMetaFlowOrchestrator",
    "PefyRagflowMemoryAdapter",
    "RagflowConnection",
    "RagflowRetrievalPolicy",
    "ReleaseClass",
    "RouteDecision",
    "RustVectorConfig",
    "RustVectorIndex",
    "StaticRagflowDatasetResolver",
    "TaskNode",
    "VectorHit",
    "VectorStats",
    "approximate_context_chars",
    "build_execution_waves",
    "burst_smoothing_offsets",
    "clean_output",
    "compact_memory_records",
    "filter_export_messages",
    "recommended_parallelism",
    "render_export_text",
    "route_mission",
    "select_execution_agencies",
]
