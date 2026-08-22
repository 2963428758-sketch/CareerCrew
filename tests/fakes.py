"""共享测试替身：BaseChatModel 子类假 LLM 与内存版 AccountStore。

create_agent（LangChain 1.x）要求真实 ``BaseChatModel`` 子类（纯鸭子类型会抛
``NotImplementedError``）；``bind_tools`` 返回 self，``_generate``/``_stream``
按预置响应序列出消息。

FakeAccountStore：认证存储唯一后端为 Postgres，单元/API 测试用 dict 内存替身
（语义与 PostgresAccountStore 对齐），真实 SQL 行为由
tests/integration/test_postgres_account_store.py 覆盖。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from careercrew_api.auth.store import ROLES, STATUSES, AccountExistsError, AccountStore, hash_token


def _now() -> datetime:
    return datetime.now(UTC)


class FakeChatModel(BaseChatModel):
    """按预置响应序列出 AIMessage 的假 LLM（支持 bind_tools 占位 + 流式）。"""

    responses: list[AIMessage] = Field(default_factory=list)

    def __init__(self, responses: list[AIMessage]) -> None:
        super().__init__(responses=list(responses))
        object.__setattr__(self, "_i", 0)

    @property
    def _llm_type(self) -> str:
        return "fake-chat-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        resp = self._next()
        content = resp.content or ""
        if content:
            for ch in content:
                yield ChatGenerationChunk(message=AIMessageChunk(content=ch))
        if resp.tool_calls:
            chunks = [
                {
                    "name": tc["name"],
                    "args": json.dumps(tc["args"], ensure_ascii=False),
                    "id": tc["id"],
                    "index": i,
                    "type": "tool_call_chunk",
                }
                for i, tc in enumerate(resp.tool_calls)
            ]
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_call_chunks=chunks)
            )
        # 真实流式模型会在流末以 usage chunk 回传 token 计量（T1.4 观测依赖此字段）
        if getattr(resp, "usage_metadata", None):
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", usage_metadata=resp.usage_metadata)
            )

    def _next(self) -> AIMessage:
        i = self._i
        object.__setattr__(self, "_i", i + 1)
        if not self.responses:
            return AIMessage(content="")
        return self.responses[i] if i < len(self.responses) else self.responses[-1]


class FakeAccountStore(AccountStore):
    """dict 内存版账号存储（语义对齐 PostgresAccountStore，测试专用）。"""

    def __init__(self) -> None:
        self.accounts: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.audit: list[dict] = []
        self.failures: dict[str, dict] = {}

    def _row(self, user_id: str) -> dict | None:
        row = self.accounts.get(user_id)
        if row is None:
            return None
        out = dict(row)
        out["must_change_password"] = bool(out.get("must_change_password", False))
        return out

    def has_accounts(self) -> bool:
        return bool(self.accounts)

    def create_first_admin(self, username: str, password_hash: str) -> dict:
        if self.accounts:
            raise AccountExistsError("an account already exists")
        now = _now().isoformat()
        self.accounts["u_001"] = {
            "id": "u_001", "username": username, "password_hash": password_hash,
            "role": "admin", "status": "active", "token_version": 0,
            "must_change_password": False, "created_at": now, "updated_at": now,
        }
        return self._public(self._row("u_001"))

    def create_account(self, username: str, password_hash: str, role: str,
                       must_change: bool = False) -> dict:
        if role not in ROLES:
            raise ValueError(f"invalid role: {role}")
        if any(a["username"] == username for a in self.accounts.values()):
            raise AccountExistsError("username already exists")
        user_id = f"u_{uuid4().hex}"
        now = _now().isoformat()
        self.accounts[user_id] = {
            "id": user_id, "username": username, "password_hash": password_hash,
            "role": role, "status": "active", "token_version": 0,
            "must_change_password": must_change, "created_at": now, "updated_at": now,
        }
        return self._public(self._row(user_id))

    def account_by_username(self, username: str) -> dict | None:
        for row in self.accounts.values():
            if row["username"] == username:
                return dict(row)
        return None

    def account_by_id(self, user_id: str) -> dict | None:
        row = self._row(user_id)
        return self._public(row) if row else None

    def list_accounts(self, offset: int, limit: int) -> tuple[list[dict], int]:
        rows = sorted(self.accounts.values(), key=lambda a: (a["created_at"], a["id"]))
        return [self._public(r) for r in rows[offset:offset + limit]], len(rows)

    def update_account(self, user_id: str, *, role: str | None = None,
                       status: str | None = None) -> dict:
        if role is not None and role not in ROLES:
            raise ValueError(f"invalid role: {role}")
        if status is not None and status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        if user_id not in self.accounts:
            raise KeyError(user_id)
        if role is not None:
            self.accounts[user_id]["role"] = role
        if status is not None:
            self.accounts[user_id]["status"] = status
        self.accounts[user_id]["updated_at"] = _now().isoformat()
        return self._public(self._row(user_id))

    def delete_account(self, user_id: str) -> bool:
        if user_id not in self.accounts:
            return False
        del self.accounts[user_id]
        # 刷新会话随账号删除一并失效（与 Postgres FK ON DELETE CASCADE 语义一致）
        for token in [t for t, s in list(self.sessions.items()) if s.get("user_id") == user_id]:
            del self.sessions[token]
        return True

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        self.accounts[user_id]["password_hash"] = password_hash
        self.accounts[user_id]["updated_at"] = _now().isoformat()

    def update_avatar(self, user_id: str, avatar_ref: str) -> None:
        if user_id not in self.accounts:
            raise KeyError(user_id)
        self.accounts[user_id]["avatar"] = avatar_ref
        self.accounts[user_id]["updated_at"] = _now().isoformat()

    def update_display_name(self, user_id: str, name: str) -> None:
        if user_id not in self.accounts:
            raise KeyError(user_id)
        self.accounts[user_id]["display_name"] = name
        self.accounts[user_id]["updated_at"] = _now().isoformat()

    def set_must_change_password(self, user_id: str, value: bool) -> None:
        self.accounts[user_id]["must_change_password"] = value
        self.accounts[user_id]["updated_at"] = _now().isoformat()

    def bump_token_version(self, user_id: str) -> int:
        if user_id not in self.accounts:
            raise KeyError(user_id)
        self.accounts[user_id]["token_version"] = int(self.accounts[user_id]["token_version"]) + 1
        return self.accounts[user_id]["token_version"]

    def create_refresh_session(self, token: str, user_id: str, expires_at: datetime) -> None:
        self.sessions[hash_token(token)] = {
            "user_id": user_id, "expires_at": expires_at, "revoked_at": None,
        }

    def rotate_refresh_session(self, old_token: str, new_token: str,
                               expires_at: datetime) -> dict | None:
        session = self.sessions.pop(hash_token(old_token), None)
        if session is None or session["revoked_at"] is not None or session["expires_at"] <= _now():
            return None
        user = self._row(session["user_id"])
        if user is None or user["status"] != "active":
            return None
        self.sessions[hash_token(new_token)] = {
            "user_id": user["id"], "expires_at": expires_at, "revoked_at": None,
        }
        return self._public(user)

    def revoke_refresh_session(self, token: str) -> None:
        session = self.sessions.get(hash_token(token))
        if session:
            session["revoked_at"] = _now()

    def revoke_all_refresh_sessions(self, user_id: str) -> int:
        count = 0
        for session in self.sessions.values():
            if session["user_id"] == user_id and session["revoked_at"] is None:
                session["revoked_at"] = _now()
                count += 1
        return count

    def revoke_other_refresh_sessions(self, user_id: str, keep_token: str) -> int:
        keep = hash_token(keep_token)
        count = 0
        for key, session in self.sessions.items():
            if key != keep and session["user_id"] == user_id and session["revoked_at"] is None:
                session["revoked_at"] = _now()
                count += 1
        return count

    def delete_expired_refresh_sessions(self, revoked_older_than_days: int = 30) -> int:
        now = _now()
        cutoff = now - timedelta(days=revoked_older_than_days)
        stale = [
            key for key, s in self.sessions.items()
            if s["expires_at"] <= now or (s["revoked_at"] is not None and s["revoked_at"] <= cutoff)
        ]
        for key in stale:
            del self.sessions[key]
        return len(stale)

    def add_audit_event(self, actor_id: str, action: str, target_user_id: str | None,
                        context: dict) -> None:
        self.audit.append({
            "actor_id": actor_id, "action": action,
            "target_user_id": target_user_id, "context": dict(context),
        })

    def login_failure_locked(self, key: str) -> tuple[bool, str | None]:
        row = self.failures.get(key)
        if row and row.get("locked_until") and row["locked_until"] > _now():
            return True, row["locked_until"].isoformat()
        return False, None

    def record_login_failure(self, key: str, *, max_failures: int,
                             window: timedelta, lock: timedelta) -> tuple[bool, str | None]:
        now = _now()
        row = self.failures.get(key)
        if row and row.get("locked_until") and row["locked_until"] > now:
            return True, row["locked_until"].isoformat()
        if row is None:
            self.failures[key] = {"failures": 1, "window_start": now, "locked_until": None}
            return False, None
        window_start = row.get("window_start") or now
        if window_start < now - window:
            failures, window_start = 1, now
        else:
            failures = int(row["failures"]) + 1
        locked_until = now + lock if failures >= max_failures else None
        self.failures[key] = {"failures": failures, "window_start": window_start,
                              "locked_until": locked_until}
        return failures >= max_failures, locked_until.isoformat() if locked_until else None

    def clear_login_failures(self, key: str) -> None:
        self.failures.pop(key, None)

