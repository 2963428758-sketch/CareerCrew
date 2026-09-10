"""Career domain: ongoing job-search records (board, materials, tasks, HR,
offers, real interviews, profile). Owner scoping is enforced at the store layer."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 看板固定阶段（§第二期：求职进度看板）
STAGES = ("待准备", "已投递", "沟通中", "面试中", "收到Offer", "已结束")
Stage = Literal["待准备", "已投递", "沟通中", "面试中", "收到Offer", "已结束"]


class CareerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="before")
    @classmethod
    def safe_text(cls, value):
        if isinstance(value, str) and any(
            (ord(char) < 32 and char not in "\t\r\n")
            or 0xD800 <= ord(char) <= 0xDFFF or ord(char) in (0xFFFE, 0xFFFF)
            for char in value
        ):
            raise ValueError("文本包含不支持的控制字符")
        return value


def validate_date(value: str) -> str:
    """公开的日期校验（YYYY-MM-DD 或空串），供 store 层复用。"""
    return _optional_date(value)


def _optional_date(value: str) -> str:
    if not value:
        return value
    import re

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("日期格式应为 YYYY-MM-DD")
    return value


# ── 看板 ──

class BoardStatusInput(CareerInput):
    stage: Stage
    next_action: str = Field(default="", max_length=500)
    next_action_date: str = Field(default="", max_length=10)
    note: str = Field(default="", max_length=2000)
    # 投递所用简历版本（版本归因用；空串 = 未标记）
    applied_version_id: str = Field(default="", max_length=100)

    @field_validator("next_action_date")
    @classmethod
    def _date(cls, value):
        return _optional_date(value)


class BoardStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)

    opportunity_id: str
    company: str
    title: str
    stage: str
    next_action: str
    next_action_date: str
    note: str
    stage_updated_at: datetime
    updated_at: datetime


class StageChange(BaseModel):
    id: str
    from_stage: str
    to_stage: str
    note: str
    created_at: datetime


# ── 素材库 ──

class MaterialInput(CareerInput):
    name: str = Field(min_length=1, max_length=200)
    background: str = Field(default="", max_length=5000)
    role: str = Field(default="", max_length=2000)
    actions: str = Field(default="", max_length=5000)
    results: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=10)
    confirmed: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, value):
        if not value.strip():
            raise ValueError("素材名称不能为空")
        return value

    @field_validator("tags")
    @classmethod
    def _tags(cls, value):
        cleaned = [str(t).strip()[:50] for t in value if str(t).strip()]
        if len(cleaned) != len(value):
            raise ValueError("标签不能为空白")
        return cleaned


class Material(MaterialInput):
    id: str
    created_at: datetime
    updated_at: datetime


# ── 行动任务 ──

class ActionItemInput(CareerInput):
    title: str = Field(min_length=1, max_length=300)
    note: str = Field(default="", max_length=1000)
    due_date: str = Field(default="", max_length=10)
    opportunity_id: str = Field(default="", max_length=100)

    @field_validator("title")
    @classmethod
    def _title(cls, value):
        if not value.strip():
            raise ValueError("任务标题不能为空")
        return value

    @field_validator("due_date")
    @classmethod
    def _date(cls, value):
        return _optional_date(value)


class ActionItem(ActionItemInput):
    id: str
    done: bool
    postponed_count: int
    dismissed: bool
    created_at: datetime
    updated_at: datetime


# ── HR 跟进 ──

class HRFollowupInput(CareerInput):
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)
    channel: str = Field(default="", max_length=100)
    content: str = Field(min_length=1, max_length=20000)
    received_at: str = Field(default="", max_length=20)
    opportunity_id: str = Field(default="", max_length=100)
    todo_note: str = Field(default="", max_length=1000)

    @field_validator("company", "content")
    @classmethod
    def _required(cls, value):
        if not value.strip():
            raise ValueError("公司与沟通内容不能为空")
        return value


class HRFollowup(HRFollowupInput):
    id: str
    reply_draft: str
    draft_confirmed: bool
    resolved: bool
    created_at: datetime
    updated_at: datetime


class HRReplyDraftInput(CareerInput):
    reply_draft: str = Field(min_length=1, max_length=10000)
    confirmed: bool = False


# ── Offer 对比 ──

class OfferInput(CareerInput):
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)
    base_salary: str = Field(default="", max_length=200)
    bonus: str = Field(default="", max_length=200)
    equity: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)
    work_mode: str = Field(default="", max_length=200)
    growth: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=2000)
    opportunity_id: str = Field(default="", max_length=100)

    @field_validator("company")
    @classmethod
    def _company(cls, value):
        if not value.strip():
            raise ValueError("公司名称不能为空")
        return value


class Offer(OfferInput):
    id: str
    created_at: datetime
    updated_at: datetime


# ── 真实面试复盘 ──

class RealInterviewQuestion(CareerInput):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(default="", max_length=10000)
    reflection: str = Field(default="", max_length=2000)


class RealInterviewInput(CareerInput):
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)
    interview_date: str = Field(default="", max_length=10)
    stage: str = Field(default="", max_length=100)
    questions: list[RealInterviewQuestion] = Field(default_factory=list, max_length=20)
    overall_reflection: str = Field(default="", max_length=5000)

    @field_validator("company")
    @classmethod
    def _company(cls, value):
        if not value.strip():
            raise ValueError("公司名称不能为空")
        return value

    @field_validator("interview_date")
    @classmethod
    def _date(cls, value):
        return _optional_date(value)


class RealInterview(RealInterviewInput):
    id: str
    weak_points: list[str]
    created_at: datetime


# ── 联系人与内推 ──

class ContactInput(CareerInput):
    contact_name: str = Field(min_length=1, max_length=120)
    company: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=120)
    channel: str = Field(default="", max_length=100)
    contact_value: str = Field(default="", max_length=300)
    opportunity_id: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=2000)
    next_contact_date: str = Field(default="", max_length=10)

    @field_validator("contact_name")
    @classmethod
    def _name(cls, value):
        if not value.strip():
            raise ValueError("联系人姓名不能为空")
        return value

    @field_validator("next_contact_date")
    @classmethod
    def _date(cls, value):
        return _optional_date(value)


class Contact(ContactInput):
    id: str
    created_at: datetime
    updated_at: datetime


# ── 求职画像（首次引导） ──

class CareerProfileInput(CareerInput):
    stage: str = Field(default="", max_length=100)
    city: str = Field(default="", max_length=100)
    goal: str = Field(default="", max_length=1000)
    onboarding_done: bool = False


class CareerProfile(CareerProfileInput):
    updated_at: datetime
