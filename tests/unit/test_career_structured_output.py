"""Career AI structured-output contracts.

These tests protect the boundary between untrusted model text and the career API.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from careercrew_core.career.structured_output import (
    ApplicationKitOutput,
    GapAnalysisOutput,
    IntelligenceBriefOutput,
    InterviewReviewOutput,
    StructuredOutputError,
    decode_json_object,
    parse_structured_output,
)


def test_decoder_extracts_fenced_object_and_preserves_braces_inside_strings() -> None:
    raw = """分析如下：
```json
{"cover_letter":"我做过 {RAG} 项目","self_intro":"介绍","greeting":"您好",\
"followup":"请问进展","thank_you":"感谢交流"}
```
请人工确认。"""

    parsed = parse_structured_output(raw, ApplicationKitOutput)

    assert parsed.cover_letter == "我做过 {RAG} 项目"
    assert parsed.thank_you == "感谢交流"


def test_decoder_skips_unbalanced_prose_brace_before_later_valid_object() -> None:
    raw = '说明里有一个未闭合括号 {，真正结果是 {"summary":"总评","strengths":[],"weaknesses":[],"practice_suggestions":[]}'

    parsed = parse_structured_output(raw, InterviewReviewOutput)

    assert parsed.summary == "总评"


def test_decoder_joins_text_content_blocks_without_accepting_non_text_payloads() -> None:
    raw = [
        {"type": "text", "text": "前言"},
        {"type": "image", "url": "https://example.invalid/private.png"},
        {"type": "text", "text": '{"company_research":"基于 JD 的推断","likely_questions":["讲讲项目"],"confirm_questions":["团队规模？"],"evidence":[]}'},
    ]

    parsed = parse_structured_output(raw, IntelligenceBriefOutput)

    assert parsed.likely_questions == ["讲讲项目"]


@pytest.mark.parametrize("raw", ["[]", "没有 JSON", 123, [{"type": "image", "url": "x"}]])
def test_decoder_rejects_non_object_or_non_text_output(raw: object) -> None:
    with pytest.raises(StructuredOutputError, match="JSON object"):
        decode_json_object(raw)


def test_application_kit_rejects_number_to_string_coercion() -> None:
    raw = ('{"cover_letter":123,"self_intro":"介绍","greeting":"您好",'
           '"followup":"跟进","thank_you":"感谢"}')

    with pytest.raises(StructuredOutputError) as exc:
        parse_structured_output(raw, ApplicationKitOutput)

    assert exc.value.reason == "schema_validation"


def test_interview_review_rejects_string_instead_of_typed_list() -> None:
    with pytest.raises(ValidationError):
        InterviewReviewOutput.model_validate({
            "summary": "总评",
            "strengths": "表达清楚",
            "weaknesses": [],
            "practice_suggestions": [],
        })


def test_intelligence_brief_enforces_list_and_string_bounds() -> None:
    with pytest.raises(ValidationError):
        IntelligenceBriefOutput.model_validate({
            "company_research": "推断",
            "likely_questions": ["问题"] * 5,
            "confirm_questions": [],
            "evidence": [],
        })
    with pytest.raises(ValidationError):
        IntelligenceBriefOutput.model_validate({
            "company_research": "推断",
            "likely_questions": ["x" * 301],
            "confirm_questions": [],
            "evidence": [],
        })


def test_gap_schema_rejects_unknown_statuses_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        GapAnalysisOutput.model_validate({
            "requirements": [{
                "requirement": "熟悉 RAG",
                "status": "almost_matched",
                "evidence": "项目经验",
                "note": "",
            }]
        })
    with pytest.raises(ValidationError):
        GapAnalysisOutput.model_validate({
            "requirements": [{
                "requirement": "熟悉 RAG",
                "status": "matched",
                "evidence": "项目经验",
                "note": "",
                "private_resume": "不应进入结构化结果",
            }]
        })
