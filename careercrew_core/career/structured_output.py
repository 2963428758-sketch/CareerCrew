"""Strict schemas and robust JSON decoding for career generation features.

Model output is untrusted input.  This module deliberately keeps extraction and
validation separate: the decoder locates one JSON object, then Pydantic enforces
the exact business shape without scalar or collection coercion.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

ShortText = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=300)
]
OptionalShortText = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, max_length=300)
]
SummaryText = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500)
]
ResearchText = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=600)
]
SectionText = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=2000)
]


class _StrictOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class StructuredOutputError(ValueError):
    """Safe parse failure that never includes the model response in its message."""

    def __init__(self, reason: Literal["invalid_json", "schema_validation"], message: str):
        super().__init__(message)
        self.reason = reason


class ApplicationKitOutput(_StrictOutput):
    cover_letter: SectionText
    self_intro: SectionText
    greeting: SectionText
    followup: SectionText
    thank_you: SectionText

    def as_sections(self) -> dict[str, str]:
        """Return the existing API's ``sections`` payload shape."""
        return self.model_dump()


class IntelligenceBriefOutput(_StrictOutput):
    company_research: ResearchText
    likely_questions: Annotated[list[ShortText], Field(min_length=1, max_length=4)]
    confirm_questions: Annotated[list[ShortText], Field(max_length=4)]
    evidence: Annotated[list[ShortText], Field(max_length=4)]


class InterviewReviewOutput(_StrictOutput):
    summary: SummaryText
    strengths: Annotated[list[ShortText], Field(max_length=3)]
    weaknesses: Annotated[list[ShortText], Field(max_length=3)]
    practice_suggestions: Annotated[list[ShortText], Field(max_length=3)]


class GapRequirementOutput(_StrictOutput):
    requirement: ShortText
    status: Literal["matched", "missing", "not_mention"]
    evidence: OptionalShortText
    note: OptionalShortText


class GapAnalysisOutput(_StrictOutput):
    requirements: Annotated[list[GapRequirementOutput], Field(min_length=1, max_length=12)]


_FENCED_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_MAX_OUTPUT_CHARS = 50_000


def _content_text(raw: object) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts = [
            block["text"]
            for block in raw
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ]
        if parts:
            return "".join(parts)
    raise StructuredOutputError("invalid_json", "Model output did not contain a JSON object")


def _as_object(candidate: str) -> dict[str, Any] | None:
    try:
        value = json.loads(candidate)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _balanced_objects(text: str) -> Iterator[str]:
    """Yield balanced ``{...}`` candidates while respecting quoted braces.

    Every opening brace is considered independently.  This lets a later valid
    object survive an earlier unmatched brace in prose.
    """
    starts = (index for index, char in enumerate(text) if char == "{")
    for start in starts:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    yield text[start:index + 1]
                    break
                if depth < 0:
                    break


def decode_json_object(raw: object) -> dict[str, Any]:
    """Extract the first valid JSON object from plain, fenced, or block output."""
    text = _content_text(raw).strip()
    if not text or len(text) > _MAX_OUTPUT_CHARS:
        raise StructuredOutputError("invalid_json", "Model output did not contain a JSON object")

    direct = _as_object(text)
    if direct is not None:
        return direct

    for fenced in _FENCED_BLOCK_RE.findall(text):
        parsed = _as_object(fenced.strip())
        if parsed is not None:
            return parsed

    for candidate in _balanced_objects(text):
        parsed = _as_object(candidate)
        if parsed is not None:
            return parsed

    raise StructuredOutputError("invalid_json", "Model output did not contain a JSON object")


def parse_structured_output[T: BaseModel](raw: object, schema: type[T]) -> T:
    """Decode a model response and validate it against an exact strict schema."""
    payload = decode_json_object(raw)
    try:
        return schema.model_validate(payload)
    except ValidationError:
        raise StructuredOutputError(
            "schema_validation", "Model JSON object did not match the required schema"
        ) from None
