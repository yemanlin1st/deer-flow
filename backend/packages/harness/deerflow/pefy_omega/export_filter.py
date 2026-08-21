"""Structured export boundary for MƐTAFLOW Ω.

Internal context must be excluded by metadata/visibility semantics before text
rendering. String stripping is only a hygiene fallback and must not be the
primary security boundary.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .humanize import OutputHygienePolicy, clean_output


class ExportVisibility(StrEnum):
    PUBLIC = "public"
    CLIENT = "client"
    INTERNAL = "internal"
    HIDDEN = "hidden"
    SECRET = "secret"


_NON_EXPORTABLE_VISIBILITY = frozenset(
    {
        ExportVisibility.INTERNAL.value,
        ExportVisibility.HIDDEN.value,
        ExportVisibility.SECRET.value,
    }
)

_NON_EXPORTABLE_CATEGORIES = frozenset(
    {
        "system_context",
        "memory_context",
        "tool_internal",
        "planner_internal",
        "chain_of_thought",
        "hidden_instruction",
        "secret_material",
        "credential_material",
        "private_prompt",
    }
)

_ALLOWED_METADATA_KEYS = frozenset(
    {
        "citation_refs",
        "source_refs",
        "document_code",
        "version",
        "classification",
        "author",
        "approval_status",
        "required_disclosure",
    }
)


@dataclass(frozen=True, slots=True)
class ExportableMessage:
    content: str
    role: str = "assistant"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExportedMessage:
    content: str
    role: str
    metadata: Mapping[str, Any]


def _should_export(message: ExportableMessage) -> bool:
    metadata = message.metadata

    if metadata.get("required_disclosure") is True:
        return True
    if metadata.get("export") is False:
        return False
    if metadata.get("internal") is True or metadata.get("hidden") is True:
        return False

    visibility = str(metadata.get("visibility", "public")).strip().lower()
    if visibility in _NON_EXPORTABLE_VISIBILITY:
        return False

    category = str(metadata.get("category", "")).strip().lower()
    if category in _NON_EXPORTABLE_CATEGORIES:
        return False

    # System messages are non-exportable by default. A deliberately exported
    # disclosure must opt in with required_disclosure above.
    if message.role.strip().lower() == "system":
        return False

    return True


def _safe_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Return an allow-listed metadata projection for the final artifact."""

    return {key: metadata[key] for key in _ALLOWED_METADATA_KEYS if key in metadata}


def filter_export_messages(
    messages: Iterable[ExportableMessage],
    *,
    hygiene_policy: OutputHygienePolicy | None = None,
) -> tuple[ExportedMessage, ...]:
    """Filter internal context structurally, then clean visible content.

    Security/confidentiality decisions happen before text cleanup. This avoids
    relying on fragile hard-coded marker removal and reduces the chance of
    deleting legitimate user text that resembles an internal tag.
    """

    policy = hygiene_policy or OutputHygienePolicy()
    exported: list[ExportedMessage] = []

    for message in messages:
        if not _should_export(message):
            continue

        cleaned = clean_output(message.content, policy)
        if not cleaned and not message.metadata.get("required_disclosure"):
            continue

        exported.append(
            ExportedMessage(
                content=cleaned,
                role=message.role,
                metadata=_safe_metadata(message.metadata),
            )
        )

    return tuple(exported)


def render_export_text(messages: Iterable[ExportedMessage]) -> str:
    """Render already-filtered messages as plain text without role scaffolding."""

    return "\n\n".join(message.content.strip() for message in messages if message.content.strip())
