from __future__ import annotations

import pytest

from deerflow.pefy_omega.export_filter import (
    ExportableMessage,
    filter_export_messages,
    render_export_text,
)
from deerflow.pefy_omega.policy import Mode
from deerflow.pefy_omega.registry import (
    METAFLOW_AGENCY,
    METAFLOW_AGENT,
    select_execution_agencies,
)
from deerflow.pefy_omega.scheduler import (
    TaskNode,
    build_execution_waves,
    burst_smoothing_offsets,
    recommended_parallelism,
)


def test_structured_export_filters_internal_context_before_text_cleanup() -> None:
    messages = (
        ExportableMessage("internal memory", role="assistant", metadata={"visibility": "internal"}),
        ExportableMessage("hidden planner", role="assistant", metadata={"category": "planner_internal"}),
        ExportableMessage("public result", role="assistant", metadata={"visibility": "public"}),
    )

    exported = filter_export_messages(messages)

    assert [message.content for message in exported] == ["public result"]


def test_public_user_text_that_resembles_internal_marker_is_not_string_stripped() -> None:
    messages = (
        ExportableMessage("The literal example <memory> belongs in this public explanation.", role="user"),
    )

    assert render_export_text(filter_export_messages(messages)) == (
        "The literal example <memory> belongs in this public explanation."
    )


def test_system_message_is_hidden_unless_it_is_required_disclosure() -> None:
    messages = (
        ExportableMessage("private system instruction", role="system"),
        ExportableMessage(
            "AI-assisted, human-reviewed disclosure required by contract.",
            role="system",
            metadata={"required_disclosure": True},
        ),
    )

    exported = filter_export_messages(messages)

    assert len(exported) == 1
    assert "required by contract" in exported[0].content


def test_export_metadata_is_allow_listed() -> None:
    exported = filter_export_messages(
        (
            ExportableMessage(
                "Result",
                metadata={
                    "citation_refs": ["source-1"],
                    "provider": "internal-provider-name",
                    "secret_debug": "never export this",
                },
            ),
        )
    )

    assert exported[0].metadata == {"citation_refs": ["source-1"]}


def test_metaflow_has_distinct_agent_and_agency_definitions() -> None:
    assert METAFLOW_AGENT.agent_id == "pefy.metaflow.omega.orchestrator"
    assert METAFLOW_AGENCY.primary_agent_id == METAFLOW_AGENT.agent_id
    assert "all-council-challenge" in METAFLOW_AGENT.capabilities


def test_execution_agency_selection_is_domain_specific_and_deduplicated() -> None:
    agencies = select_execution_agencies(("video", "media", "data"))

    assert agencies.count("DRAMACLAW Ω STUDIO") == 1
    assert "Data & Intelligence Agency™" in agencies
    assert "Quality & Delivery Agency™" in agencies


def test_scheduler_parallelizes_only_independent_tasks() -> None:
    waves = build_execution_waves(
        (
            TaskNode("research", "Research", priority=90),
            TaskNode("benchmark", "Benchmark", priority=80),
            TaskNode("synthesis", "Synthesize", depends_on=("research", "benchmark")),
        ),
        mode=Mode.STANDARD,
    )

    assert {task.task_id for task in waves[0].tasks} == {"research", "benchmark"}
    assert [task.task_id for task in waves[1].tasks] == ["synthesis"]


def test_scheduler_fails_closed_on_dependency_cycle() -> None:
    with pytest.raises(ValueError, match="cycle"):
        build_execution_waves(
            (
                TaskNode("a", "A", depends_on=("b",)),
                TaskNode("b", "B", depends_on=("a",)),
            )
        )


def test_mode_parallelism_limits_sensitive_execution() -> None:
    assert recommended_parallelism(Mode.ULTRA) > recommended_parallelism(Mode.WARROOM)
    assert recommended_parallelism(Mode.SOVEREIGN) == 4


def test_burst_smoothing_provides_runtime_launch_hints() -> None:
    assert burst_smoothing_offsets(4, mode=Mode.STANDARD, base_interval_ms=50) == (0, 50, 100, 150)
    assert burst_smoothing_offsets(3, mode=Mode.SOVEREIGN, base_interval_ms=50) == (0, 100, 200)
