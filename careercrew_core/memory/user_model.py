"""长期 User Model 结构化读写（C5）。

UserModelStore：load / save / update，字段路径白名单约束（非法字段拒绝）。
存储：data/user_model.json（单用户 MVP；多用户按 user_id 分文件，后期）。
"""
from __future__ import annotations

import json
from pathlib import Path

from careercrew_core.memory.types import UserModel

# 允许 profile_update 更新的字段路径（白名单）
ALLOWED_FIELDS: set[str] = {
    "profile.skills",
    "profile.level",
    "profile.direction",
    "profile.experience_years",
    "target_companies",
    "preferences.salary_min",
    "preferences.salary_max",
    "preferences.city",
    "preferences.work_mode",
}


class UserModelStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self, user_id: str) -> UserModel:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            data.setdefault("user_id", user_id)
            return UserModel.model_validate(data)
        return UserModel(user_id=user_id)

    def save(self, model: UserModel) -> None:
        self.path.write_text(model.model_dump_json(indent=2), encoding="utf-8")

    def update(self, user_id: str, fields: dict) -> UserModel:
        """结构化更新；字段必须在白名单内，否则拒绝。"""
        for k in fields:
            if k not in ALLOWED_FIELDS:
                raise ValueError(f"非法字段: {k}，允许: {sorted(ALLOWED_FIELDS)}")
        model = self.load(user_id)
        data = model.model_dump()
        for k, v in fields.items():
            parts = k.split(".")
            d = data
            for p in parts[:-1]:
                d = d[p]
            d[parts[-1]] = v
        model = UserModel.model_validate(data)
        self.save(model)
        return model
