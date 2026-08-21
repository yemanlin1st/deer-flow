"""Human-readable output hygiene for MƐTAFLOW Ω.

This module removes accidental chatbot and formatting artifacts. It is not a
mechanism for falsifying authorship, bypassing disclosure duties, or defeating
provenance controls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200D\u2060\uFEFF]")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)

# Only deterministic, generic assistant residue belongs here. Domain-specific
# language is deliberately excluded so useful content is not silently erased.
_CHATBOT_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*as an ai(?: language model)?[,.:]?\s*.*$", re.IGNORECASE),
    re.compile(r"^\s*i hope (?:this|that) helps[.!]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*let me know if you(?:'d| would)? like(?: me)? to .*?[.!]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*feel free to (?:ask|reach out).*?[.!]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*here(?:'s| is) (?:a|the) (?:comprehensive|detailed) (?:answer|response).*?$", re.IGNORECASE),
)

_REQUIRED_DISCLOSURE_MARKERS: tuple[str, ...] = (
    "AI-assisted, human-reviewed",
    "AI-assisted and human-reviewed",
    "artificial intelligence assistance",
    "use of AI",
    "use of artificial intelligence",
)


@dataclass(frozen=True, slots=True)
class OutputHygienePolicy:
    remove_zero_width: bool = True
    remove_generic_chatbot_residue: bool = True
    normalize_whitespace: bool = True
    preserve_required_disclosure: bool = True


def _is_required_disclosure(line: str) -> bool:
    lowered = line.casefold()
    return any(marker.casefold() in lowered for marker in _REQUIRED_DISCLOSURE_MARKERS)


def _clean_plain_segment(segment: str, policy: OutputHygienePolicy) -> str:
    if policy.remove_zero_width:
        segment = _ZERO_WIDTH_RE.sub("", segment)

    if policy.remove_generic_chatbot_residue:
        kept: list[str] = []
        for line in segment.splitlines():
            if policy.preserve_required_disclosure and _is_required_disclosure(line):
                kept.append(line)
                continue
            if any(pattern.match(line) for pattern in _CHATBOT_LINE_PATTERNS):
                continue
            kept.append(line)
        segment = "\n".join(kept)

    if policy.normalize_whitespace:
        segment = _TRAILING_WS_RE.sub("", segment)
        segment = _MULTI_BLANK_RE.sub("\n\n", segment)

    return segment


def clean_output(text: str, policy: OutputHygienePolicy | None = None) -> str:
    """Clean normal prose while preserving fenced code blocks exactly.

    Required provenance/disclosure text is preserved when policy requires it.
    The function is intentionally conservative: it cleans obvious residue but
    does not paraphrase substantive user content or remove citations.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    policy = policy or OutputHygienePolicy()
    if not text:
        return text

    # Split on fenced code blocks. Odd indexes are code and remain untouched.
    parts = re.split(r"(```[\s\S]*?```)", text)
    cleaned: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 1:
            cleaned.append(part)
        else:
            cleaned.append(_clean_plain_segment(part, policy))

    return "".join(cleaned).strip()
