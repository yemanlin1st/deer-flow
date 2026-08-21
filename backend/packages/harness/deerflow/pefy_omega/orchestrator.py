"""Runtime-neutral orchestration contract for MƐTAFLOW Ω."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from .export_filter import ExportableMessage, filter_export_messages, render_export_text
from .humanize import OutputHygienePolicy, clean_output
from .memory_budget import (
    MemoryBudgetPolicy,
    approximate_context_chars,
    compact_memory_records,
)
from .policy import MissionContext, ReleaseClass, RouteDecision, route_mission
from .registry import select_execution_agencies


class ChallengeAdapter(Protocol):
    """Bridge to PEA/counsellor/council challenge services."""

    def challenge(
        self,
        *,
        mission: MissionContext,
        route: RouteDecision,
        challenge_functions: Sequence[str],
    ) -> Sequence[Mapping[str, Any]]: ...


class EvidenceAdapter(Protocol):
    """Bridge to the PEFY evidence/lineage fabric."""

    def record(self, event_type: str, payload: Mapping[str, Any]) -> str | None: ...


class MemoryAdapter(Protocol):
    """Bridge to tenant/project-scoped memory retrieval."""

    def retrieve(self, *, mission: MissionContext, query: str) -> Sequence[Mapping[str, Any]]: ...


class RuntimeAdapter(Protocol):
    """Bridge to DeerFlow, LangGraph, local workers, or another runtime."""

    def dispatch(self, execution_packet: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class PreparedMission:
    mission: MissionContext
    route: RouteDecision
    prior_context: tuple[Mapping[str, Any], ...]
    challenges: tuple[Mapping[str, Any], ...]
    execution_agencies: tuple[str, ...]
    execution_packet: Mapping[str, Any]
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FinalizedOutput:
    mission_id: str
    content: str
    mode: str
    release_class: str
    blocked_actions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    generated_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class _NullChallengeAdapter:
    """Safe fallback that records every required challenge function as pending."""

    def challenge(
        self,
        *,
        mission: MissionContext,
        route: RouteDecision,
        challenge_functions: Sequence[str],
    ) -> Sequence[Mapping[str, Any]]:
        return tuple(
            {
                "challenge_function": name,
                "status": "PENDING_ADAPTER",
                "depth": route.challenge_depth,
                "mission_id": mission.mission_id,
            }
            for name in challenge_functions
        )


class PefyMetaFlowOrchestrator:
    """PEFY mission router above replaceable agent-harness runtimes.

    It prepares policy, bounded memory, full council challenge and evidence
    context before dispatch. Consequential actions remain blocked unless the
    mission carries explicit owner authority.
    """

    def __init__(
        self,
        *,
        challenge_adapter: ChallengeAdapter | None = None,
        evidence_adapter: EvidenceAdapter | None = None,
        memory_adapter: MemoryAdapter | None = None,
        runtime_adapter: RuntimeAdapter | None = None,
        output_hygiene_policy: OutputHygienePolicy | None = None,
        memory_budget_policy: MemoryBudgetPolicy | None = None,
    ) -> None:
        self._challenge = challenge_adapter or _NullChallengeAdapter()
        self._evidence = evidence_adapter
        self._memory = memory_adapter
        self._runtime = runtime_adapter
        self._hygiene = output_hygiene_policy or OutputHygienePolicy()
        self._memory_budget = memory_budget_policy or MemoryBudgetPolicy()
        self._memory_budget.validate()

    def _record(self, event_type: str, payload: Mapping[str, Any]) -> str | None:
        if self._evidence is None:
            return None
        return self._evidence.record(event_type, payload)

    def prepare_mission(self, mission: MissionContext) -> PreparedMission:
        route = route_mission(mission)
        evidence_refs: list[str] = []

        ref = self._record(
            "mission.routed",
            {
                "mission_id": mission.mission_id,
                "mode": route.mode.value,
                "release_class": mission.release_class.value,
                "reasons": route.reasons,
                "hard_gates": route.hard_gates,
                "blocked_actions": route.blocked_actions,
                "tenant_context_present": bool(mission.tenant_id),
                "project_context_present": bool(mission.project_id),
            },
        )
        if ref:
            evidence_refs.append(ref)

        tenant_isolation_required = "tenant-isolation" in route.hard_gates
        if tenant_isolation_required and not (mission.tenant_id or "").strip():
            self._record(
                "mission.blocked",
                {
                    "mission_id": mission.mission_id,
                    "reason": "tenant-context-missing",
                    "gate": "tenant-isolation",
                },
            )
            raise PermissionError(
                "tenant_id is required before confidential, restricted or client-scoped execution"
            )

        prior_context: tuple[Mapping[str, Any], ...] = ()
        if self._memory is not None:
            raw_context = self._memory.retrieve(mission=mission, query=mission.objective)
            raw_count = len(raw_context)
            prior_context = compact_memory_records(raw_context, self._memory_budget)
            del raw_context

            ref = self._record(
                "memory.retrieved",
                {
                    "mission_id": mission.mission_id,
                    "tenant_context_present": bool(mission.tenant_id),
                    "project_context_present": bool(mission.project_id),
                    "input_record_count": raw_count,
                    "retained_record_count": len(prior_context),
                    "retained_string_chars": approximate_context_chars(prior_context),
                    "max_records": self._memory_budget.max_records,
                    "max_total_chars": self._memory_budget.max_total_chars,
                    "max_string_chars": self._memory_budget.max_string_chars,
                    "deduplicate": self._memory_budget.deduplicate,
                },
            )
            if ref:
                evidence_refs.append(ref)

        challenge_functions = route.counsellors + route.councils
        challenges = tuple(
            self._challenge.challenge(
                mission=mission,
                route=route,
                challenge_functions=challenge_functions,
            )
        )

        challenged_names = {
            str(item.get("challenge_function", ""))
            for item in challenges
            if isinstance(item, Mapping)
        }
        missing = [name for name in challenge_functions if name not in challenged_names]
        if missing:
            raise RuntimeError(f"mandatory PEFY challenge functions missing: {missing}")

        ref = self._record(
            "council.challenge.completed",
            {
                "mission_id": mission.mission_id,
                "depth": route.challenge_depth,
                "challenge_count": len(challenges),
                "challenge_functions": challenge_functions,
            },
        )
        if ref:
            evidence_refs.append(ref)

        execution_agencies = select_execution_agencies(mission.domains)
        execution_packet: dict[str, Any] = {
            "schema": "pefy.metaflow.omega.execution.v1",
            "mission": asdict(mission),
            "route": asdict(route),
            "prior_context": prior_context,
            "challenges": challenges,
            "execution_agencies": execution_agencies,
            "constraints": {
                "deny_unknown_tools": True,
                "least_privilege": True,
                "production_self_mutation": False,
                "preserve_required_provenance": True,
                "structured_export_filter": True,
                "bounded_memory_context": True,
                "tenant_isolation_required": tenant_isolation_required,
                "memory_context_max_records": self._memory_budget.max_records,
                "memory_context_max_total_chars": self._memory_budget.max_total_chars,
                "blocked_actions": route.blocked_actions,
            },
            "acceptance": {
                "evidence_required": route.evidence_required,
                "humanization_gate": True,
                "structured_export_gate": True,
                "memory_budget_gate": True,
                "tenant_context_gate": tenant_isolation_required,
                "release_gate": True,
            },
        }

        return PreparedMission(
            mission=mission,
            route=route,
            prior_context=prior_context,
            challenges=challenges,
            execution_agencies=execution_agencies,
            execution_packet=execution_packet,
            evidence_refs=tuple(evidence_refs),
        )

    def dispatch(self, prepared: PreparedMission) -> Mapping[str, Any]:
        if self._runtime is None:
            raise RuntimeError("runtime adapter is not configured")
        if prepared.route.blocked_actions:
            raise PermissionError(
                "consequential actions are blocked pending explicit owner approval: "
                + ", ".join(prepared.route.blocked_actions)
            )

        result = self._runtime.dispatch(prepared.execution_packet)
        self._record(
            "task.dispatched",
            {
                "mission_id": prepared.mission.mission_id,
                "mode": prepared.route.mode.value,
                "execution_agencies": prepared.execution_agencies,
                "runtime_result_keys": sorted(str(k) for k in result.keys()),
            },
        )
        return result

    def _assert_release_ready(self, prepared: PreparedMission) -> None:
        if prepared.mission.release_class is ReleaseClass.PRIVATE_WORKING:
            return
        if prepared.route.blocked_actions:
            raise PermissionError("release blocked by unapproved consequential actions")

        non_releasable = []
        for challenge in prepared.challenges:
            status = str(challenge.get("status", "")).strip().upper()
            if status in {"PENDING_ADAPTER", "BLOCK", "FAILED", "ERROR"}:
                non_releasable.append(
                    f"{challenge.get('challenge_function', 'unknown')}={status or 'MISSING'}"
                )
        if non_releasable:
            raise PermissionError(
                "release blocked until council challenge is resolved: " + ", ".join(non_releasable)
            )

    def finalize_messages(
        self,
        prepared: PreparedMission,
        messages: Sequence[ExportableMessage],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> FinalizedOutput:
        """Filter internal context structurally before final text rendering."""

        exported = filter_export_messages(messages, hygiene_policy=self._hygiene)
        rendered = render_export_text(exported)
        self._record(
            "structured_export.completed",
            {
                "mission_id": prepared.mission.mission_id,
                "input_message_count": len(messages),
                "exported_message_count": len(exported),
            },
        )
        return self.finalize_output(prepared, rendered, metadata=metadata)

    def finalize_output(
        self,
        prepared: PreparedMission,
        content: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> FinalizedOutput:
        self._assert_release_ready(prepared)
        cleaned = clean_output(content, self._hygiene)
        refs = list(prepared.evidence_refs)

        ref = self._record(
            "humanization.completed",
            {
                "mission_id": prepared.mission.mission_id,
                "input_chars": len(content),
                "output_chars": len(cleaned),
                "required_provenance_preserved": self._hygiene.preserve_required_disclosure,
            },
        )
        if ref:
            refs.append(ref)

        ref = self._record(
            "release.gated",
            {
                "mission_id": prepared.mission.mission_id,
                "release_class": prepared.mission.release_class.value,
                "blocked_actions": prepared.route.blocked_actions,
                "challenge_count": len(prepared.challenges),
            },
        )
        if ref:
            refs.append(ref)

        return FinalizedOutput(
            mission_id=prepared.mission.mission_id,
            content=cleaned,
            mode=prepared.route.mode.value,
            release_class=prepared.mission.release_class.value,
            blocked_actions=prepared.route.blocked_actions,
            evidence_refs=tuple(refs),
            generated_at=datetime.now(UTC).isoformat(),
            metadata=dict(metadata or {}),
        )
