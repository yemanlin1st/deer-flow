from __future__ import annotations

import pytest

from deerflow.pefy_omega.humanize import clean_output
from deerflow.pefy_omega.orchestrator import PefyMetaFlowOrchestrator
from deerflow.pefy_omega.policy import (
    ALL_COUNCILS,
    ALL_COUNSELLORS,
    MissionContext,
    Mode,
    ReleaseClass,
    route_mission,
)


def test_all_counsellors_and_councils_are_mandatory() -> None:
    mission = MissionContext(mission_id="M-001", objective="Prepare a concise internal note")
    route = route_mission(mission)

    assert route.counsellors == ALL_COUNSELLORS
    assert route.councils == ALL_COUNCILS
    assert len(route.counsellors) == 5
    assert len(route.councils) == 13
    assert route.challenge_depth == "compact"


def test_latency_sensitive_low_risk_mission_uses_flash() -> None:
    mission = MissionContext(
        mission_id="M-002",
        objective="Summarize a non-sensitive local note",
        latency_sensitive=True,
    )

    assert route_mission(mission).mode is Mode.FLASH


def test_confidential_mission_forces_sovereign_mode() -> None:
    mission = MissionContext(
        mission_id="M-003",
        objective="Analyze restricted project material",
        confidential=True,
        release_class=ReleaseClass.RESTRICTED_CLIENT,
    )
    route = route_mission(mission)

    assert route.mode is Mode.SOVEREIGN
    assert "tenant-isolation" in route.hard_gates
    assert "private-runtime-preference" in route.hard_gates


def test_consequential_action_forces_warroom_and_blocks_without_approval() -> None:
    mission = MissionContext(
        mission_id="M-004",
        objective="Deploy a production change",
        domains=("production", "cybersecurity"),
        requested_actions=("production_deploy",),
    )
    route = route_mission(mission)

    assert route.mode is Mode.WARROOM
    assert route.blocked_actions == ("production_deploy",)
    assert "explicit-human-authority" in route.hard_gates


def test_explicit_owner_approval_clears_policy_block_but_keeps_warroom() -> None:
    mission = MissionContext(
        mission_id="M-005",
        objective="Deploy an approved production change",
        requested_actions=("production_deploy",),
        owner_approved_consequential_actions=True,
    )
    route = route_mission(mission)

    assert route.mode is Mode.WARROOM
    assert route.blocked_actions == ()
    assert "approval-record" in route.evidence_required


def test_orchestrator_prepares_all_18_challenge_functions() -> None:
    mission = MissionContext(mission_id="M-006", objective="Prepare a governed plan")
    prepared = PefyMetaFlowOrchestrator().prepare_mission(mission)

    assert len(prepared.challenges) == 18
    names = {item["challenge_function"] for item in prepared.challenges}
    assert names == set(ALL_COUNSELLORS + ALL_COUNCILS)
    assert all(item["status"] == "PENDING_ADAPTER" for item in prepared.challenges)


def test_dispatch_refuses_unapproved_consequential_action() -> None:
    mission = MissionContext(
        mission_id="M-007",
        objective="Publish externally",
        requested_actions=("external_publish",),
    )
    orchestrator = PefyMetaFlowOrchestrator(runtime_adapter=object())  # type: ignore[arg-type]
    prepared = orchestrator.prepare_mission(mission)

    with pytest.raises(PermissionError):
        orchestrator.dispatch(prepared)


def test_output_hygiene_removes_chatbot_residue_and_zero_width() -> None:
    source = "As an AI language model, I can help.\n\nUseful\u200b result.\n\nI hope this helps!"

    assert clean_output(source) == "Useful result."


def test_output_hygiene_preserves_required_provenance_and_code_block() -> None:
    source = (
        "AI-assisted, human-reviewed and validated by the named author.\n\n"
        "```python\n"
        "text = 'As an AI language model, do not alter code'\n"
        "```\n\n"
        "Let me know if you'd like me to expand it."
    )
    cleaned = clean_output(source)

    assert "AI-assisted, human-reviewed and validated by the named author." in cleaned
    assert "text = 'As an AI language model, do not alter code'" in cleaned
    assert "Let me know" not in cleaned
