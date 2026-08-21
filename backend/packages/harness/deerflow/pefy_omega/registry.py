"""PEFY agency and agent registry primitives for MƐTAFLOW Ω."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    agent_id: str
    name: str
    role: str
    capabilities: tuple[str, ...]
    autonomy: str = "governed"
    owner_scope: str = "PEFY-GG"


@dataclass(frozen=True, slots=True)
class AgencyDefinition:
    agency_id: str
    name: str
    mission: str
    domains: tuple[str, ...]
    primary_agent_id: str
    delegates: tuple[str, ...] = ()


METAFLOW_AGENT = AgentDefinition(
    agent_id="pefy.metaflow.omega.orchestrator",
    name="MƐTAFLOW Ω Chief Orchestrator Agent™",
    role="Mission classification, full council challenge orchestration, execution routing, synthesis and release gating.",
    capabilities=(
        "mission-intake",
        "policy-routing",
        "all-council-challenge",
        "context-engineering",
        "parallel-execution-planning",
        "runtime-routing",
        "evidence-coordination",
        "deep-loop-quality",
        "humanization",
        "release-gating",
    ),
)

METAFLOW_AGENCY = AgencyDefinition(
    agency_id="pefy.metaflow.omega.agency",
    name="MƐTAFLOW Ω Sovereign Orchestration Agency™",
    mission="Coordinate PEFY specialist agencies and replaceable runtimes into governed, fast, evidence-aware production.",
    domains=("orchestration", "research", "delivery", "governance", "cross-domain"),
    primary_agent_id=METAFLOW_AGENT.agent_id,
    delegates=(
        "Quality & Delivery Agency™",
        "Data & Intelligence Agency™",
        "Finance & Value Agency™",
        "Legal & IP Agency™",
        "GitOps & Release Agency™",
        "R&D/Product Agency™",
        "Executive & War Room Agency™",
        "Knowledge & Evidence Agency™",
        "Language & Comms Agency™",
        "Impact Agency™",
        "DRAMACLAW Ω STUDIO",
        "PEFY DevSecOps/Cyber Agency",
    ),
)


_DOMAIN_AGENCY_ROUTES: dict[str, tuple[str, ...]] = {
    "video": ("DRAMACLAW Ω STUDIO", "Language & Comms Agency™", "Quality & Delivery Agency™"),
    "media": ("DRAMACLAW Ω STUDIO", "Language & Comms Agency™", "Quality & Delivery Agency™"),
    "cybersecurity": ("PEFY DevSecOps/Cyber Agency", "Quality & Delivery Agency™"),
    "devsecops": ("PEFY DevSecOps/Cyber Agency", "GitOps & Release Agency™"),
    "software": ("R&D/Product Agency™", "GitOps & Release Agency™", "Quality & Delivery Agency™"),
    "data": ("Data & Intelligence Agency™", "Knowledge & Evidence Agency™"),
    "analytics": ("Data & Intelligence Agency™", "Knowledge & Evidence Agency™"),
    "finance": ("Finance & Value Agency™", "Knowledge & Evidence Agency™"),
    "legal": ("Legal & IP Agency™", "Knowledge & Evidence Agency™"),
    "ip": ("Legal & IP Agency™", "Brand/IP governance"),
    "research": ("Knowledge & Evidence Agency™", "Data & Intelligence Agency™"),
    "strategy": ("Executive & War Room Agency™", "Finance & Value Agency™"),
    "document": ("Language & Comms Agency™", "Quality & Delivery Agency™"),
    "presentation": ("Language & Comms Agency™", "Quality & Delivery Agency™"),
    "impact": ("Impact Agency™", "Data & Intelligence Agency™"),
}


def select_execution_agencies(domains: Iterable[str]) -> tuple[str, ...]:
    """Return a de-duplicated specialist execution set after council challenge.

    This is deliberately separate from the mandatory 18-function governance
    challenge. Every council challenges the mission, while only relevant
    agencies execute it.
    """

    selected: list[str] = []
    for raw_domain in domains:
        domain = raw_domain.strip().lower()
        for agency in _DOMAIN_AGENCY_ROUTES.get(domain, ()):
            if agency not in selected:
                selected.append(agency)

    if not selected:
        selected.extend(("Quality & Delivery Agency™", "Knowledge & Evidence Agency™"))

    return tuple(selected)
