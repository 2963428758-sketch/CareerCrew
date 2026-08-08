"""业务级评估（L2）：转化率 / 通过率 / offer 数，从情景记忆事件统计。"""
from __future__ import annotations

from careercrew_core.memory.episodic import EpisodicMemory


class BusinessEvaluator:
    """从情景记忆（application / interview_qa / offer 事件）统计求职漏斗。"""

    def __init__(self, episodic: EpisodicMemory) -> None:
        self._episodic = episodic

    def stats(self) -> dict:
        entries = self._episodic._read_all()
        apps = [e for e in entries if e.type == "application"]
        interviews = [e for e in entries if e.type == "interview_qa"]
        offers = [e for e in entries if e.type == "offer"]
        return {
            "applications": len(apps),
            "interviews": len(interviews),
            "offers": len(offers),
            "apply_to_interview_rate": round(len(interviews) / len(apps), 3) if apps else 0.0,
            "interview_pass_rate": round(len(offers) / len(interviews), 3) if interviews else 0.0,
        }
