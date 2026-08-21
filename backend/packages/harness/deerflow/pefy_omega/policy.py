"""Mission classification, council routing and hard governance gates for MƐTAFLOW Ω."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable


class Mode(StrEnum):
    FLASH = "FLASH"
    STANDARD = "STANDARD"
    PRO = "PRO"
    ULTRA = "ULTRA"
    SOVEREIGN = "SOVEREIGN"
    WARROOM = "WARROOM"


class ReleaseClass(StrEnum):
    PRIVATE_WORKING = "PRIVATE_WORKING"
    INTERNAL_CONFIDENTIAL = "INTERNAL_CONFIDENTIAL"
    RESTRICTED_CLIENT = "RESTRICTED_CLIENT"
    PUBLIC_NEUTRALIZED = "PUBLIC_NEUTRALIZED"


ALL_COUNSELLORS: tuple[str, ...] = (
    "Strategy & Growth",
    "IMS & Operations",
    "Finance & Cash",
    "Digital, Data & Cyber",
    "Brand, IP & Customer",
)

ALL_COUNCILS: tuple[str, ...] = (
    "Security & Governance",
    "Deep Loop",
    "Strategy",
    "Quality & Delivery",
    "Data & Intelligence",
    "Finance & Value",
    "Legal & IP",
    "GitOps & Release",
    "R&D / Product",
    "Executive & War Room",
    "Knowledge & Evidence",
    "Language & Communications",
    "Impact",
)

ALL_CHALLENGE_FUNCTIONS: tuple[str, ...] = ALL_COUNSELLORS + ALL_COUNCILS

_HIGH_RISK_DOMAINS = frozenset(
    {
        "legal",
        "financial",
        "payment",
        "cybersecurity",
        "safety",
        "health",
        "hr",
        "production",
        "identity",
        "secrets",
        "privacy",
        "public",
    }
)

_CONSEQUENTIAL_ACTIONS = frozenset(
    {
        "write",
        "delete",
        "send",
        "payment",
        "signature",
        "secret_access",
        "production_deploy",
        "account_wide_change",
        "external_publish",
    }
)


@dataclass(frozen=True, slots=True)
class MissionContext:
    """Minimum policy context required before execution begins."""

    mission_id: str
    objective: str
    tenant_id: str | None = None
    project_id: str | None = None
    domains: tuple[str, ...] = ()
    release_class: ReleaseClass = ReleaseClass.PRIVATE_WORKING
    confidential: bool = False
    client_data: bool = False
    personal_data: bool = False
    cross_domain: bool = False
    requested_actions: tuple[str, ...] = ()
    requested_mode: Mode | None = None
    requires_current_facts: bool = False
    requires_external_tools: bool = False
    latency_sensitive: bool = False
    owner_approved_consequential_actions: bool = False


@dataclass(frozen=True, slots=True)
class RouteDecision:
    mode: Mode
    counsellors: tuple[str, ...]
    councils: tuple[str, ...]
    challenge_depth: str
    hard_gates: tuple[str, ...]
    blocked_actions: tuple[str, ...]
    evidence_required: tuple[str, ...]
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def can_execute_consequential_actions(self) -> bool:
        return not self.blocked_actions


def _normalized(values: Iterable[str]) -> frozenset[str]:
    return frozenset(v.strip().lower() for v in values if v and v.strip())


def route_mission(context: MissionContext) -> RouteDecision:
    """Select execution mode and mandatory governance controls.

    All five counsellors and all thirteen specialist councils are always
    included. Low-risk work uses a compact challenge depth to limit latency;
    higher-risk work receives a full or adversarial challenge pass.
    """

    domains = _normalized(context.domains)
    actions = _normalized(context.requested_actions)

    high_risk_domain = bool(domains & _HIGH_RISK_DOMAINS)
    consequential = actions & _CONSEQUENTIAL_ACTIONS
    restricted = context.release_class in {
        ReleaseClass.INTERNAL_CONFIDENTIAL,
        ReleaseClass.RESTRICTED_CLIENT,
    }
    isolation_required = context.confidential or context.client_data or restricted

    reasons: list[str] = []
    gates: list[str] = [
        "mission-classification",
        "all-counsellors-challenge",
        "all-councils-challenge",
        "evidence-integrity",
        "humanization-output-hygiene",
        "release-classification",
    ]
    evidence: list[str] = ["decision-record", "challenge-record", "release-record"]
    blocked: list[str] = []

    if consequential:
        mode = Mode.WARROOM
        reasons.append("consequential action requested")
        gates.extend(
            [
                "explicit-human-authority",
                "rollback-plan",
                "immutable-audit-event",
                "security-and-ip-review",
            ]
        )
        evidence.extend(["approval-record", "rollback-evidence", "audit-event"])
        if not context.owner_approved_consequential_actions:
            blocked.extend(sorted(consequential))
    elif isolation_required:
        mode = Mode.SOVEREIGN
        reasons.append("confidential or restricted information")
        gates.extend(
            [
                "tenant-isolation",
                "tenant-context",
                "minimum-necessary-context",
                "private-runtime-preference",
            ]
        )
        evidence.extend(["data-classification-record", "tenant-context-record"])
        if not context.tenant_id:
            reasons.append("tenant context required before governed execution")
    elif high_risk_domain:
        mode = Mode.ULTRA
        reasons.append("high-risk domain")
        gates.extend(["domain-verification", "independent-challenge"])
        evidence.append("verification-record")
    elif context.cross_domain or len(domains) >= 3:
        mode = Mode.PRO
        reasons.append("cross-domain orchestration")
    elif context.latency_sensitive and not context.requires_external_tools:
        mode = Mode.FLASH
        reasons.append("latency-sensitive low-risk mission")
    else:
        mode = Mode.STANDARD
        reasons.append("standard governed execution")

    if context.requested_mode is not None:
        # User choice can raise rigor but must not lower a policy-forced mode.
        rank = {
            Mode.FLASH: 0,
            Mode.STANDARD: 1,
            Mode.PRO: 2,
            Mode.ULTRA: 3,
            Mode.SOVEREIGN: 4,
            Mode.WARROOM: 5,
        }
        if rank[context.requested_mode] > rank[mode]:
            mode = context.requested_mode
            reasons.append("user requested stricter execution mode")

    if context.requires_current_facts:
        gates.append("fresh-source-verification")
        evidence.append("source-lineage")

    if context.requires_external_tools:
        gates.extend(["tool-admission", "least-privilege"])
        evidence.append("tool-call-log")

    if mode in {Mode.WARROOM, Mode.SOVEREIGN, Mode.ULTRA}:
        challenge_depth = "adversarial"
    elif mode is Mode.PRO:
        challenge_depth = "full"
    else:
        challenge_depth = "compact"

    return RouteDecision(
        mode=mode,
        counsellors=ALL_COUNSELLORS,
        councils=ALL_COUNCILS,
        challenge_depth=challenge_depth,
        hard_gates=tuple(dict.fromkeys(gates)),
        blocked_actions=tuple(dict.fromkeys(blocked)),
        evidence_required=tuple(dict.fromkeys(evidence)),
        reasons=tuple(reasons),
    )
