"""Runtime-neutral orchestration contract for MƐTAFLOW Ω."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Protocol, Sequence

from .humanize import OutputHygienePolicy, clean_output
from .policy import MissionContext, RouteDecision, route_mission


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

    The class is intentionally runtime-neutral. It prepares policy, memory,
    council and evidence context before dispatch. Consequential actions remain
    blocked unless the mission context carries explicit owner authority.
    """

    def __init__(
        self,
        *,
        challenge_adapter: ChallengeAdapter | None = None,
        evidence_adapter: EvidenceAdapter | None = None,
        memory_adapter: MemoryAdapter | None = None,
        runtime_adapter: RuntimeAdapter | None = None,
        output_hygiene_policy: OutputHygienePolicy | None = None,
    ) -> None:
        self._challenge = challenge_adapter or _NullChallengeAdapter()
        self._evidence = evidence_adapter
        self._memory = memory_adapter
        self._runtime = runtime_adapter
        self._hygiene = output_hygiene_policy or OutputHygienePolicy()

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
            },
        )
        if ref:
            evidence_refs.append(ref)

        prior_context: tuple[Mapping[str, Any], ...] = ()
        if self._memory is not None:
            prior_context = tuple(self._memory.retrieve(mission=mission, query=mission.objective))

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

        execution_packet: dict[str, Any] = {
            "schema": "pefy.metaflow.omega.execution.v1",
            "mission": asdict(mission),
            "route": asdict(route),
            "prior_context": prior_context,
            "challenges": challenges,
            "constraints": {
                "deny_unknown_tools": True,
                "least_privilege": True,
                "production_self_mutation": False,
                "preserve_required_provenance": True,
                "blocked_actions": route.blocked_actions,
            },
            "acceptance": {
                "evidence_required": route.evidence_required,
                "humanization_gate": True,
                "release_gate": True,
            },
        }

        return PreparedMission(
            mission=mission,
            route=route,
            prior_context=prior_context,
            challenges=challenges,
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
                "runtime_result_keys": sorted(str(k) for k in result.keys()),
            },
        )
        return result

    def finalize_output(
        self,
        prepared: PreparedMission,
        content: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> FinalizedOutput:
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
