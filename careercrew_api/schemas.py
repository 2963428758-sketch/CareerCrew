"""pydantic 请求/响应模型（§4 API 端点）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ── 通用 ──


class HealthResponse(BaseModel):
    status: str = "ok"
    model: str = ""
    embedding: str = ""
    vector_store: str = ""
    ready: bool = False
    error: str | None = None


# ── Chat（M1 对话闭环）──


class MatchRequest(BaseModel):
    intent: str
    thread_id: str = "m1"
    user_id: str = "u_001"


class ResumeRequest(BaseModel):
    jd_text: str
    thread_id: str = "m1"
    user_id: str = "u_001"


# ── Interview ──


class QuestionRequest(BaseModel):
    topic: str = ""
    user_id: str = "u_001"


class ScoreRequest(BaseModel):
    question: str
    answer: str
    max_score: int = 10


class ScoreResponse(BaseModel):
    score: float
    feedback: str


class RecordRequest(BaseModel):
    entries: list[dict]


class RecordResponse(BaseModel):
    saved: int


# ── Resume ──


class GenerateRequest(BaseModel):
    user_resume: str
    jd: str = ""
    thread_id: str = "m1"
    user_id: str = "u_001"


class UploadResponse(BaseModel):
    filename: str
    doc_type: str  # image | text | pdf | ...
    content: str
    truncated: bool = False
    char_count: int = 0


# ── Consult（会诊）──


class ConsultRequest(BaseModel):
    question: str
    agents: list[str] = Field(default_factory=lambda: ["salary_negotiator", "career_planner"])
    user_id: str = "u_001"
