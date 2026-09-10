"""Owner-scoped token/cost ledger with atomic daily and monthly budgets.

The ledger intentionally accepts operational metadata only.  Prompt text,
answers, tool arguments, and user supplied free-form content never enter the
event contract.  ``FakeMemoryDb`` is used by unit/API tests; the PostgreSQL
path uses the same public methods and row locks for budget reservations.
"""
from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,149}$")
_MODULE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,49}$")
_PERIODS = frozenset({"daily", "monthly"})
_SCOPES = frozenset({"user", "module"})
_EVENT_STATUSES = frozenset({"completed", "failed", "cancelled", "rejected"})
_RESERVATION_STATUSES = frozenset({"reserved", "settled", "released"})
_ZERO = Decimal("0")


class UsageError(RuntimeError):
    """Base class for usage governance errors."""


class UsageValidationError(UsageError, ValueError):
    """The usage or budget input is outside the safe contract."""


class BudgetExceeded(UsageError):
    """A hard budget boundary rejected a new model reservation."""

    def __init__(
        self,
        reason: str,
        *,
        scope_type: str = "user",
        scope_key: str = "*",
        period: str = "daily",
        downgrade_model: str | None = None,
    ) -> None:
        self.reason = reason
        self.scope_type = scope_type
        self.scope_key = scope_key
        self.period = period
        self.downgrade_model = downgrade_model
        super().__init__(self._message())

    def _message(self) -> str:
        labels = f"{self.scope_type}:{self.scope_key}/{self.period}"
        if self.reason == "unknown_pricing":
            return f"当前模型没有价格卡，无法在预算 {labels} 下安全调用"
        if self.reason == "cost_budget":
            return f"费用预算已达到上限（{labels}）"
        return f"Token 预算已达到上限（{labels}）"


def _now() -> datetime:
    return datetime.now(UTC)


def _owner(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 64:
        raise UsageValidationError("owner_id 无效")
    value = value.strip()
    if any(ord(char) < 32 for char in value):
        raise UsageValidationError("owner_id 无效")
    return value


def _module(value: str) -> str:
    value = str(value or "").strip()
    if not _MODULE_RE.fullmatch(value):
        raise UsageValidationError("module 必须是低基数标识")
    return value


def _label(value: str, field: str, maximum: int = 150) -> str:
    value = str(value or "").strip()
    if not value or len(value) > maximum or not _LABEL_RE.fullmatch(value):
        raise UsageValidationError(f"{field} 必须是安全标识")
    return value


def _tokens(value: int | None, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UsageValidationError(f"{field} 必须是非负整数")
    return value


def _money(value: Decimal | float | int | str | None, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise UsageValidationError(f"{field} 必须是非负金额") from exc
    if not parsed.is_finite() or parsed < _ZERO:
        raise UsageValidationError(f"{field} 必须是非负金额")
    return parsed.quantize(Decimal("0.00000001"))


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    normalized = value.normalize()
    return format(normalized, "f")


def _as_datetime(value: datetime | date | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=UTC)
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _period_start(period: Literal["daily", "monthly"], at: datetime) -> datetime:
    if period == "daily":
        return datetime(at.year, at.month, at.day, tzinfo=UTC)
    return datetime(at.year, at.month, 1, tzinfo=UTC)


def _public(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _public(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


class PriceBook:
    """Versioned price cards keyed by ``provider:model`` or model name."""

    def __init__(self, cards: Mapping[str, Mapping[str, Any]] | None = None, *, version: str = "unpriced"):
        self.version = _label(version, "pricing_version", 80)
        self._cards: dict[str, tuple[Decimal, Decimal]] = {}
        for key, card in (cards or {}).items():
            key = _label(str(key), "price_key", 180)
            if not isinstance(card, Mapping):
                raise UsageValidationError("价格卡格式无效")
            input_rate = _money(card.get("input_per_million"), "input_per_million")
            output_rate = _money(card.get("output_per_million"), "output_per_million")
            if input_rate is None or output_rate is None:
                raise UsageValidationError("价格卡必须同时提供输入和输出价格")
            self._cards[key] = input_rate, output_rate

    def quote(
        self,
        provider: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> Decimal | None:
        if input_tokens is None or output_tokens is None:
            return None
        card = self._cards.get(f"{provider}:{model}") or self._cards.get(model)
        if card is None:
            return None
        input_rate, output_rate = card
        return (
            Decimal(input_tokens) * input_rate / Decimal(1_000_000)
            + Decimal(output_tokens) * output_rate / Decimal(1_000_000)
        ).quantize(Decimal("0.00000001"))


class UsageLedger:
    """Token/cost events and budget reservations for one database."""

    def __init__(self, db, *, pricing: PriceBook | None = None) -> None:
        self.db = db
        self.pricing = pricing or PriceBook()
        self._fake = db.__class__.__name__ == "FakeMemoryDb"
        self._fallback_lock = threading.RLock()

    def _state(self) -> dict[str, Any]:
        if not hasattr(self.db, "_usage_ledger"):
            self.db._usage_ledger = {"events": {}, "budgets": {}, "reservations": {}}
        state = self.db._usage_ledger
        for key in ("events", "budgets", "reservations"):
            state.setdefault(key, {})
        return state

    def _lock(self):
        return getattr(self.db, "write_lock", self._fallback_lock)

    def _pg(self, callback):
        borrow = getattr(self.db, "_borrow", None)
        if borrow is None:
            raise UsageValidationError("用量数据库不可用")
        with self.db.write_lock, borrow() as conn:
            return callback(conn)

    def set_budget(
        self,
        owner_id: str,
        *,
        scope_type: Literal["user", "module"] = "user",
        scope_key: str = "*",
        period: Literal["daily", "monthly"] = "daily",
        token_limit: int | None = None,
        cost_limit_usd: Decimal | float | int | str | None = None,
        soft_limit_ratio: float = 0.8,
        downgrade_model: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        owner_id = _owner(owner_id)
        if scope_type not in _SCOPES or period not in _PERIODS:
            raise UsageValidationError("scope_type 或 period 无效")
        if scope_type == "user":
            if scope_key != "*":
                raise UsageValidationError("用户预算 scope_key 必须为 *")
        else:
            scope_key = _module(scope_key)
        token_limit = _tokens(token_limit, "token_limit")
        cost_limit = _money(cost_limit_usd, "cost_limit_usd")
        if token_limit is None and cost_limit is None:
            raise UsageValidationError("预算至少需要设置 token_limit 或 cost_limit_usd")
        try:
            ratio = float(soft_limit_ratio)
        except (TypeError, ValueError) as exc:
            raise UsageValidationError("soft_limit_ratio 无效") from exc
        if not 0 < ratio <= 1:
            raise UsageValidationError("soft_limit_ratio 必须在 0 到 1 之间")
        if downgrade_model is not None:
            downgrade_model = _label(downgrade_model, "downgrade_model")
        now = _now().isoformat()
        policy = {
            "owner_id": owner_id,
            "scope_type": scope_type,
            "scope_key": scope_key,
            "period": period,
            "token_limit": token_limit,
            "cost_limit_usd": cost_limit,
            "soft_limit_ratio": ratio,
            "downgrade_model": downgrade_model,
            "enabled": bool(enabled),
            "updated_at": now,
        }
        key = (owner_id, scope_type, scope_key, period)
        if self._fake:
            with self._lock():
                self._state()["budgets"][key] = policy
                return _public(dict(policy))

        def _save(conn):
            conn.execute(
                """INSERT INTO usage_budgets
                   (owner_id,scope_type,scope_key,period,token_limit,cost_limit_usd,
                    soft_limit_ratio,downgrade_model,enabled,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (owner_id,scope_type,scope_key,period) DO UPDATE SET
                    token_limit=EXCLUDED.token_limit,cost_limit_usd=EXCLUDED.cost_limit_usd,
                    soft_limit_ratio=EXCLUDED.soft_limit_ratio,downgrade_model=EXCLUDED.downgrade_model,
                    enabled=EXCLUDED.enabled,updated_at=EXCLUDED.updated_at""",
                (owner_id, scope_type, scope_key, period, token_limit, cost_limit,
                 ratio, downgrade_model, bool(enabled), now),
            )
            return _public(dict(policy))

        return self._pg(_save)

    def budgets(self, owner_id: str) -> list[dict[str, Any]]:
        owner_id = _owner(owner_id)
        if self._fake:
            with self._lock():
                rows = [dict(row) for row in self._state()["budgets"].values() if row["owner_id"] == owner_id]
            rows.sort(key=lambda row: (row["scope_type"], row["scope_key"], row["period"]))
            return [_public(row) for row in rows]

        def _read(conn):
            rows = conn.execute(
                "SELECT owner_id,scope_type,scope_key,period,token_limit,cost_limit_usd,soft_limit_ratio,downgrade_model,enabled,updated_at "
                "FROM usage_budgets WHERE owner_id=%s ORDER BY scope_type,scope_key,period",
                (owner_id,),
            ).fetchall()
            return [_public(dict(row)) for row in rows]

        return self._pg(_read)

    def reserve(
        self,
        owner_id: str,
        *,
        module: str,
        provider: str,
        model: str,
        estimated_tokens: int,
        estimated_input_tokens: int | None = None,
        estimated_output_tokens: int | None = None,
        estimated_cost_usd: Decimal | float | int | str | None = None,
        source_request_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        owner_id = _owner(owner_id)
        module = _module(module)
        provider = _label(provider, "provider", 80)
        model = _label(model, "model")
        estimated_tokens = _tokens(estimated_tokens, "estimated_tokens")
        assert estimated_tokens is not None
        estimated_input_tokens = _tokens(estimated_input_tokens, "estimated_input_tokens")
        estimated_output_tokens = _tokens(estimated_output_tokens, "estimated_output_tokens")
        estimated_cost = _money(estimated_cost_usd, "estimated_cost_usd")
        if estimated_cost is None:
            estimated_cost = self.pricing.quote(
                provider, model, estimated_input_tokens, estimated_output_tokens,
            )
        if source_request_id is not None:
            source_request_id = _label(source_request_id, "source_request_id", 128)
        at = (now or _now()).astimezone(UTC)

        if self._fake:
            with self._lock():
                return self._reserve_fake(
                    owner_id, module, provider, model, estimated_tokens, estimated_cost,
                    source_request_id, at,
                )

        def _reserve_pg(conn):
            policies = [dict(row) for row in conn.execute(
                "SELECT owner_id,scope_type,scope_key,period,token_limit,cost_limit_usd,soft_limit_ratio,downgrade_model,enabled,updated_at "
                "FROM usage_budgets WHERE owner_id=%s AND enabled=true AND "
                "((scope_type='user' AND scope_key='*') OR (scope_type='module' AND scope_key=%s)) "
                "ORDER BY scope_type,scope_key,period FOR UPDATE",
                (owner_id, module),
            ).fetchall()]
            if not policies:
                return None
            if source_request_id:
                existing = conn.execute(
                    "SELECT id::text AS id,owner_id,module,provider,model,estimated_tokens,estimated_cost_usd,status,created_at "
                    "FROM usage_reservations WHERE owner_id=%s AND source_request_id=%s AND status='reserved'",
                    (owner_id, source_request_id),
                ).fetchone()
                if existing:
                    return self._reservation_public(dict(existing))
            for policy in policies:
                usage = self._pg_period_totals(conn, owner_id, module if policy["scope_type"] == "module" else None, policy["period"], at)
                reserved = self._pg_reserved_totals(conn, owner_id, module if policy["scope_type"] == "module" else None, policy["period"], at)
                self._check_policy(policy, usage, reserved, estimated_tokens, estimated_cost)
            reservation_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO usage_reservations (id,owner_id,module,provider,model,estimated_tokens,estimated_cost_usd,status,source_request_id,created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'reserved',%s,%s,%s)",
                (reservation_id, owner_id, module, provider, model, estimated_tokens, estimated_cost,
                 source_request_id, at.isoformat(), at.isoformat()),
            )
            return {
                "reservation_id": reservation_id, "estimated_tokens": estimated_tokens,
                "estimated_cost_usd": _decimal_text(estimated_cost), "status": "reserved",
                "recommended_model": self._recommended_model(policies, owner_id, module, at, estimated_tokens, estimated_cost, conn),
                "downgrade_reason": self._downgrade_reason(policies, owner_id, module, at, estimated_tokens, estimated_cost, conn),
            }

        return self._pg(_reserve_pg)

    def _reserve_fake(
        self, owner_id: str, module: str, provider: str, model: str,
        estimated_tokens: int, estimated_cost: Decimal | None,
        source_request_id: str | None, at: datetime,
    ) -> dict[str, Any] | None:
        state = self._state()
        policies = [
            row for row in state["budgets"].values()
            if row["owner_id"] == owner_id and row["enabled"]
            and ((row["scope_type"] == "user" and row["scope_key"] == "*")
                 or (row["scope_type"] == "module" and row["scope_key"] == module))
        ]
        if not policies:
            return None
        if source_request_id:
            existing = next(
                (row for row in state["reservations"].values()
                 if row["owner_id"] == owner_id and row.get("source_request_id") == source_request_id
                 and row["status"] == "reserved"),
                None,
            )
            if existing:
                return self._reservation_public(existing)
        for policy in policies:
            usage = self._fake_period_totals(owner_id, module if policy["scope_type"] == "module" else None, policy["period"], at)
            reserved = self._fake_reserved_totals(owner_id, module if policy["scope_type"] == "module" else None, policy["period"], at)
            self._check_policy(policy, usage, reserved, estimated_tokens, estimated_cost)
        recommendation, reason = self._fake_recommendation(policies, owner_id, module, at, estimated_tokens, estimated_cost)
        reservation_id = str(uuid.uuid4())
        row = {
            "id": reservation_id, "owner_id": owner_id, "module": module,
            "provider": provider, "model": model, "estimated_tokens": estimated_tokens,
            "estimated_cost_usd": estimated_cost, "status": "reserved",
            "source_request_id": source_request_id, "created_at": at.isoformat(),
            "updated_at": at.isoformat(), "recommended_model": recommendation,
            "downgrade_reason": reason,
        }
        state["reservations"][reservation_id] = row
        return self._reservation_public(row)

    @staticmethod
    def _check_policy(
        policy: dict[str, Any], usage: dict[str, Any], reserved: dict[str, Any],
        estimated_tokens: int, estimated_cost: Decimal | None,
    ) -> None:
        projected_tokens = int(usage["total_tokens"] + reserved["total_tokens"] + estimated_tokens)
        token_limit = policy.get("token_limit")
        if token_limit is not None and projected_tokens > int(token_limit):
            raise BudgetExceeded(
                "token_budget", scope_type=policy["scope_type"], scope_key=policy["scope_key"],
                period=policy["period"], downgrade_model=policy.get("downgrade_model"),
            )
        cost_limit = policy.get("cost_limit_usd")
        if cost_limit is not None:
            if estimated_cost is None:
                raise BudgetExceeded(
                    "unknown_pricing", scope_type=policy["scope_type"], scope_key=policy["scope_key"],
                    period=policy["period"], downgrade_model=policy.get("downgrade_model"),
                )
            projected_cost = usage["priced_cost"] + reserved["priced_cost"] + estimated_cost
            if projected_cost > Decimal(str(cost_limit)):
                raise BudgetExceeded(
                    "cost_budget", scope_type=policy["scope_type"], scope_key=policy["scope_key"],
                    period=policy["period"], downgrade_model=policy.get("downgrade_model"),
                )

    @staticmethod
    def _recommendation_from_policies(
        policies: list[dict[str, Any]], projected_tokens: list[tuple[dict[str, Any], int, Decimal | None]],
    ) -> tuple[str | None, str | None]:
        for policy, tokens, cost in projected_tokens:
            limit = policy.get("token_limit")
            cost_limit = policy.get("cost_limit_usd")
            soft = False
            if limit is not None and tokens >= int(Decimal(str(limit)) * Decimal(str(policy.get("soft_limit_ratio", 0.8)))):
                soft = True
            if cost_limit is not None and cost is not None:
                # Cost soft thresholds are applied only when a known quote exists.
                if cost >= Decimal(str(cost_limit)) * Decimal(str(policy.get("soft_limit_ratio", 0.8))):
                    soft = True
            if soft and policy.get("downgrade_model"):
                return str(policy["downgrade_model"]), "budget_soft_limit"
        return None, None

    def _fake_recommendation(self, policies, owner_id, module, at, estimated_tokens, estimated_cost):
        projected = []
        for policy in policies:
            usage = self._fake_period_totals(owner_id, module if policy["scope_type"] == "module" else None, policy["period"], at)
            reserved = self._fake_reserved_totals(owner_id, module if policy["scope_type"] == "module" else None, policy["period"], at)
            projected.append((policy, usage["total_tokens"] + reserved["total_tokens"] + estimated_tokens,
                              usage["priced_cost"] + reserved["priced_cost"] + (estimated_cost or _ZERO)))
        return self._recommendation_from_policies(policies, projected)

    def _recommended_model(self, policies, owner_id, module, at, estimated_tokens, estimated_cost, conn):
        projected = []
        for policy in policies:
            usage = self._pg_period_totals(conn, owner_id, module if policy["scope_type"] == "module" else None, policy["period"], at)
            reserved = self._pg_reserved_totals(conn, owner_id, module if policy["scope_type"] == "module" else None, policy["period"], at)
            projected.append((policy, usage["total_tokens"] + reserved["total_tokens"] + estimated_tokens,
                              usage["priced_cost"] + reserved["priced_cost"] + (estimated_cost or _ZERO)))
        return self._recommendation_from_policies(policies, projected)[0]

    def _downgrade_reason(self, policies, owner_id, module, at, estimated_tokens, estimated_cost, conn):
        projected = []
        for policy in policies:
            usage = self._pg_period_totals(conn, owner_id, module if policy["scope_type"] == "module" else None, policy["period"], at)
            reserved = self._pg_reserved_totals(conn, owner_id, module if policy["scope_type"] == "module" else None, policy["period"], at)
            projected.append((policy, usage["total_tokens"] + reserved["total_tokens"] + estimated_tokens,
                              usage["priced_cost"] + reserved["priced_cost"] + (estimated_cost or _ZERO)))
        return self._recommendation_from_policies(policies, projected)[1]

    @staticmethod
    def _reservation_public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "reservation_id": str(row.get("id") or row.get("reservation_id")),
            "estimated_tokens": int(row.get("estimated_tokens") or 0),
            "estimated_cost_usd": _decimal_text(_money(row.get("estimated_cost_usd"), "estimated_cost_usd")),
            "status": str(row.get("status") or "reserved"),
            "recommended_model": row.get("recommended_model"),
            "downgrade_reason": row.get("downgrade_reason"),
        }

    def release(self, owner_id: str, reservation_id: str) -> dict[str, Any]:
        owner_id = _owner(owner_id)
        reservation_id = _label(reservation_id, "reservation_id", 80)
        if self._fake:
            with self._lock():
                row = self._state()["reservations"].get(reservation_id)
                if not row or row["owner_id"] != owner_id:
                    raise UsageValidationError("预留不存在或无权访问")
                if row["status"] == "reserved":
                    row["status"] = "released"
                    row["updated_at"] = _now().isoformat()
                return self._reservation_public(row)

        def _release(conn):
            row = conn.execute(
                "UPDATE usage_reservations SET status='released',updated_at=now() WHERE id=%s AND owner_id=%s AND status='reserved' RETURNING id::text AS id,estimated_tokens,estimated_cost_usd,status",
                (reservation_id, owner_id),
            ).fetchone()
            if not row:
                raise UsageValidationError("预留不存在、已结算或无权访问")
            return self._reservation_public(dict(row))

        return self._pg(_release)

    def record(
        self,
        owner_id: str,
        *,
        module: str,
        provider: str,
        model: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        status: Literal["completed", "failed", "cancelled", "rejected"] = "completed",
        reservation_id: str | None = None,
        source_event_id: str | None = None,
        downgrade_reason: str | None = None,
        occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        owner_id = _owner(owner_id)
        module = _module(module)
        provider = _label(provider, "provider", 80)
        model = _label(model, "model")
        input_tokens = _tokens(input_tokens, "input_tokens")
        output_tokens = _tokens(output_tokens, "output_tokens")
        total_tokens = _tokens(total_tokens, "total_tokens")
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        if status not in _EVENT_STATUSES:
            raise UsageValidationError("status 无效")
        if reservation_id is not None:
            reservation_id = _label(reservation_id, "reservation_id", 80)
        if source_event_id is not None:
            source_event_id = _label(source_event_id, "source_event_id", 128)
        if downgrade_reason is not None:
            downgrade_reason = _label(downgrade_reason, "downgrade_reason", 80)
        at = (occurred_at or _now()).astimezone(UTC)
        cost = self.pricing.quote(provider, model, input_tokens, output_tokens)
        event_id = str(uuid.uuid4())
        row = {
            "id": event_id, "owner_id": owner_id, "module": module,
            "provider": provider, "model": model, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "total_tokens": total_tokens,
            "estimated_cost_usd": cost, "pricing_version": self.pricing.version,
            "pricing_status": "known" if cost is not None else "unknown",
            "status": status, "reservation_id": reservation_id,
            "source_event_id": source_event_id, "downgrade_reason": downgrade_reason,
            "occurred_at": at.isoformat(),
        }
        if self._fake:
            with self._lock():
                state = self._state()
                if source_event_id:
                    existing = next(
                        (item for item in state["events"].values()
                         if item["owner_id"] == owner_id and item.get("source_event_id") == source_event_id),
                        None,
                    )
                    if existing:
                        return _public(dict(existing))
                if reservation_id:
                    reservation = state["reservations"].get(reservation_id)
                    if not reservation or reservation["owner_id"] != owner_id or reservation["status"] != "reserved":
                        raise UsageValidationError("预留不存在、已结算或无权访问")
                    reservation["status"] = "settled"
                    reservation["updated_at"] = at.isoformat()
                state["events"][event_id] = row
                return _public(dict(row))

        def _record_pg(conn):
            if source_event_id:
                existing = conn.execute(
                    "SELECT id::text AS id,owner_id,module,provider,model,input_tokens,output_tokens,total_tokens,estimated_cost_usd,pricing_version,pricing_status,status,reservation_id::text AS reservation_id,source_event_id,downgrade_reason,occurred_at FROM usage_events WHERE owner_id=%s AND source_event_id=%s",
                    (owner_id, source_event_id),
                ).fetchone()
                if existing:
                    return _public(dict(existing))
            if reservation_id:
                reservation = conn.execute(
                    "SELECT id::text AS id FROM usage_reservations WHERE id=%s AND owner_id=%s AND status='reserved' FOR UPDATE",
                    (reservation_id, owner_id),
                ).fetchone()
                if not reservation:
                    raise UsageValidationError("预留不存在、已结算或无权访问")
            conn.execute(
                """INSERT INTO usage_events
                   (id,owner_id,module,provider,model,input_tokens,output_tokens,total_tokens,
                    estimated_cost_usd,pricing_version,pricing_status,status,reservation_id,
                    source_event_id,downgrade_reason,occurred_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (event_id, owner_id, module, provider, model, input_tokens, output_tokens,
                 total_tokens, cost, self.pricing.version, row["pricing_status"], status,
                 reservation_id, source_event_id, downgrade_reason, at.isoformat()),
            )
            if reservation_id:
                conn.execute("UPDATE usage_reservations SET status='settled',updated_at=now() WHERE id=%s", (reservation_id,))
            return _public(row)

        return self._pg(_record_pg)

    def summary(
        self,
        owner_id: str,
        *,
        period: Literal["daily", "monthly"] = "daily",
        module: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        owner_id = _owner(owner_id)
        if period not in _PERIODS:
            raise UsageValidationError("period 必须为 daily 或 monthly")
        if module is not None:
            module = _module(module)
        at = (now or _now()).astimezone(UTC)
        start = _period_start(period, at)
        if self._fake:
            with self._lock():
                events = [dict(row) for row in self._state()["events"].values() if row["owner_id"] == owner_id]
                reservations = [dict(row) for row in self._state()["reservations"].values() if row["owner_id"] == owner_id]
                budgets = [dict(row) for row in self._state()["budgets"].values() if row["owner_id"] == owner_id and row["period"] == period]
        else:
            def _read(conn):
                events = [dict(row) for row in conn.execute(
                    "SELECT id::text AS id,owner_id,module,provider,model,input_tokens,output_tokens,total_tokens,estimated_cost_usd,pricing_version,pricing_status,status,reservation_id::text AS reservation_id,source_event_id,downgrade_reason,occurred_at FROM usage_events WHERE owner_id=%s AND occurred_at >= %s ORDER BY occurred_at DESC",
                    (owner_id, start.isoformat()),
                ).fetchall()]
                reservations = [dict(row) for row in conn.execute(
                    "SELECT id::text AS id,owner_id,module,provider,model,estimated_tokens,estimated_cost_usd,status,source_request_id,created_at,updated_at FROM usage_reservations WHERE owner_id=%s AND status='reserved' AND created_at >= %s",
                    (owner_id, start.isoformat()),
                ).fetchall()]
                budgets = [dict(row) for row in conn.execute(
                    "SELECT owner_id,scope_type,scope_key,period,token_limit,cost_limit_usd,soft_limit_ratio,downgrade_model,enabled,updated_at FROM usage_budgets WHERE owner_id=%s AND period=%s",
                    (owner_id, period),
                ).fetchall()]
                return events, reservations, budgets
            events, reservations, budgets = self._pg(_read)
        events = [row for row in events if (module is None or row.get("module") == module) and row.get("status") != "rejected"
                  and (_as_datetime(row.get("occurred_at")) or start) >= start]
        reservations = [row for row in reservations if (module is None or row.get("module") == module)
                        and row.get("status") == "reserved"
                        and (_as_datetime(row.get("created_at")) or start) >= start]
        result = self._summary_rows(events, owner_id, period, module, start, reservations)
        result["budgets"] = [_public(row) for row in budgets if module is None or row.get("scope_type") == "user" or row.get("scope_key") == module]
        return result

    def _summary_rows(self, events, owner_id, period, module, start, reservations):
        input_total = sum(int(row.get("input_tokens") or 0) for row in events)
        output_total = sum(int(row.get("output_tokens") or 0) for row in events)
        total = sum(int(row.get("total_tokens") or 0) for row in events)
        priced = [
            _money(row.get("estimated_cost_usd"), "estimated_cost_usd")
            for row in events if row.get("estimated_cost_usd") is not None
        ]
        priced = [item for item in priced if item is not None]
        unknown = sum(1 for row in events if row.get("estimated_cost_usd") is None)
        by_module: dict[str, dict[str, Any]] = {}
        for row in events:
            name = str(row.get("module") or "unknown")
            item = by_module.setdefault(name, {"events": 0, "total_tokens": 0, "estimated_cost_usd": _ZERO})
            item["events"] += 1
            item["total_tokens"] += int(row.get("total_tokens") or 0)
            if row.get("estimated_cost_usd") is not None:
                item["estimated_cost_usd"] += _money(row["estimated_cost_usd"], "estimated_cost_usd") or _ZERO
        for item in by_module.values():
            item["estimated_cost_usd"] = _decimal_text(item["estimated_cost_usd"])
        reserved_tokens = sum(int(row.get("estimated_tokens") or 0) for row in reservations)
        reserved_cost = sum((_money(row.get("estimated_cost_usd"), "estimated_cost_usd") or _ZERO) for row in reservations)
        return {
            "owner_id": owner_id, "period": period, "module": module,
            "period_start": start.isoformat(), "events": len(events),
            "input_tokens": input_total, "output_tokens": output_total,
            "total_tokens": total,
            "estimated_cost_usd": _decimal_text(sum(priced, _ZERO)) if unknown == 0 else None,
            "priced_cost_usd": _decimal_text(sum(priced, _ZERO)),
            "pricing_complete": unknown == 0,
            "unknown_price_events": unknown,
            "reserved_tokens": reserved_tokens,
            "reserved_cost_usd": _decimal_text(reserved_cost),
            "by_module": dict(sorted(by_module.items())),
        }

    def _fake_period_totals(self, owner_id, module, period, at):
        start = _period_start(period, at)
        events = [row for row in self._state()["events"].values()
                  if row["owner_id"] == owner_id and row.get("status") != "rejected"
                  and (module is None or row.get("module") == module)
                  and (_as_datetime(row.get("occurred_at")) or start) >= start]
        return self._totals(events)

    def _fake_reserved_totals(self, owner_id, module, period, at):
        start = _period_start(period, at)
        rows = [row for row in self._state()["reservations"].values()
                if row["owner_id"] == owner_id and row.get("status") == "reserved"
                and (module is None or row.get("module") == module)
                and (_as_datetime(row.get("created_at")) or start) >= start]
        return {
            "total_tokens": sum(int(row.get("estimated_tokens") or 0) for row in rows),
            "priced_cost": sum((_money(row.get("estimated_cost_usd"), "estimated_cost_usd") or _ZERO) for row in rows),
        }

    @staticmethod
    def _totals(events):
        return {
            "total_tokens": sum(int(row.get("total_tokens") or 0) for row in events),
            "priced_cost": sum((_money(row.get("estimated_cost_usd"), "estimated_cost_usd") or _ZERO) for row in events),
        }

    @staticmethod
    def _pg_period_totals(conn, owner_id, module, period, at):
        start = _period_start(period, at)
        sql = "SELECT COALESCE(SUM(total_tokens),0) AS total_tokens, COALESCE(SUM(estimated_cost_usd),0) AS priced_cost FROM usage_events WHERE owner_id=%s AND status<>'rejected' AND occurred_at >= %s"
        params: list[Any] = [owner_id, start.isoformat()]
        if module:
            sql += " AND module=%s"
            params.append(module)
        row = conn.execute(sql, tuple(params)).fetchone()
        return {"total_tokens": int(row["total_tokens"] or 0), "priced_cost": _money(row["priced_cost"], "priced_cost") or _ZERO}

    @staticmethod
    def _pg_reserved_totals(conn, owner_id, module, period, at):
        start = _period_start(period, at)
        sql = "SELECT COALESCE(SUM(estimated_tokens),0) AS total_tokens, COALESCE(SUM(estimated_cost_usd),0) AS priced_cost FROM usage_reservations WHERE owner_id=%s AND status='reserved' AND created_at >= %s"
        params: list[Any] = [owner_id, start.isoformat()]
        if module:
            sql += " AND module=%s"
            params.append(module)
        row = conn.execute(sql, tuple(params)).fetchone()
        return {"total_tokens": int(row["total_tokens"] or 0), "priced_cost": _money(row["priced_cost"], "priced_cost") or _ZERO}


__all__ = ["BudgetExceeded", "PriceBook", "UsageError", "UsageLedger", "UsageValidationError"]
