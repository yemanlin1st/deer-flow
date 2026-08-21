"""Bound semantic/project memory before it enters MƐTAFLOW execution packets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class MemoryBudgetPolicy:
    max_records: int = 12
    max_total_chars: int = 12_000
    max_string_chars: int = 1_200
    max_scalar_fields: int = 16
    max_list_items: int = 12
    allow_nested_mappings: bool = False
    deduplicate: bool = True

    def validate(self) -> None:
        values = {
            "max_records": self.max_records,
            "max_total_chars": self.max_total_chars,
            "max_string_chars": self.max_string_chars,
            "max_scalar_fields": self.max_scalar_fields,
            "max_list_items": self.max_list_items,
        }
        invalid = [name for name, value in values.items() if value <= 0]
        if invalid:
            raise ValueError(f"memory budget values must be positive: {invalid}")


_PRIORITY_FIELDS = (
    "memory_id",
    "score",
    "kind",
    "summary",
    "excerpt",
    "evidence_ref",
    "source_ref",
    "updated_at",
    "project_id",
    "tenant_id",
    "decision_id",
    "status",
)

_DENIED_FIELD_FRAGMENTS = (
    "secret",
    "password",
    "credential",
    "token",
    "private_key",
    "raw_payload",
    "full_payload",
    "binary",
    "embedding",
    "vector",
    "blob",
)


def _is_denied_field(name: str) -> bool:
    normalized = name.strip().lower()
    return any(fragment in normalized for fragment in _DENIED_FIELD_FRAGMENTS)


def _compact_value(value: Any, policy: MemoryBudgetPolicy) -> Any | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[: policy.max_string_chars]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    if isinstance(value, Mapping):
        if not policy.allow_nested_mappings:
            return None
        compact: dict[str, Any] = {}
        for key, nested in list(value.items())[: policy.max_scalar_fields]:
            name = str(key)
            if _is_denied_field(name):
                continue
            converted = _compact_value(nested, policy)
            if converted is not None:
                compact[name] = converted
        return compact
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        compact_items: list[Any] = []
        for item in value[: policy.max_list_items]:
            converted = _compact_value(item, policy)
            if converted is not None and not isinstance(converted, (dict, list, tuple)):
                compact_items.append(converted)
        return tuple(compact_items)
    return None


def _record_key(record: Mapping[str, Any], index: int) -> tuple[str, str]:
    for field in ("evidence_ref", "source_ref", "memory_id", "decision_id"):
        value = record.get(field)
        if value not in (None, ""):
            return field, str(value)
    return "position", str(index)


def _ordered_fields(record: Mapping[str, Any]) -> tuple[str, ...]:
    priority = [field for field in _PRIORITY_FIELDS if field in record]
    remaining = sorted(str(field) for field in record if str(field) not in priority)
    return tuple(priority + remaining)


def compact_memory_records(
    records: Sequence[Mapping[str, Any]],
    policy: MemoryBudgetPolicy | None = None,
) -> tuple[Mapping[str, Any], ...]:
    """Return a deterministic, bounded, non-blob memory projection.

    This is a defense-in-depth boundary. Backend-specific adapters should
    already return compact results, but every adapter passes through this gate
    before its records enter a mission execution packet.
    """

    active = policy or MemoryBudgetPolicy()
    active.validate()

    output: list[Mapping[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    total_chars = 0

    for index, record in enumerate(records):
        if len(output) >= active.max_records:
            break
        if not isinstance(record, Mapping):
            continue

        key = _record_key(record, index)
        if active.deduplicate and key in seen:
            continue

        compact: dict[str, Any] = {}
        fields_used = 0
        for field in _ordered_fields(record):
            if fields_used >= active.max_scalar_fields:
                break
            if _is_denied_field(field):
                continue
            converted = _compact_value(record.get(field), active)
            if converted is None:
                continue

            added_chars = len(converted) if isinstance(converted, str) else 0
            remaining_chars = active.max_total_chars - total_chars
            if added_chars > remaining_chars:
                if remaining_chars <= 0:
                    break
                converted = converted[:remaining_chars]
                added_chars = len(converted)

            compact[field] = converted
            fields_used += 1
            total_chars += added_chars

            if total_chars >= active.max_total_chars:
                break

        if compact:
            output.append(compact)
            seen.add(key)

        if total_chars >= active.max_total_chars:
            break

    return tuple(output)


def approximate_context_chars(records: Sequence[Mapping[str, Any]]) -> int:
    """Cheap observable for the bounded string payload entering execution."""

    total = 0
    for record in records:
        for value in record.values():
            if isinstance(value, str):
                total += len(value)
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                total += sum(len(item) for item in value if isinstance(item, str))
    return total
