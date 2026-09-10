"""Small dependency-free Prometheus registry for service-level counters.

Labels are deliberately restricted to route templates, status classes, and
coarse operation names.  User IDs, document IDs, model names, prompts, and
free-form error strings are never emitted as labels.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from threading import RLock

_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
_SAFE_VALUE = re.compile(r"^[a-zA-Z0-9_:. /-]{1,100}$")
_MODULE_VALUE = re.compile(r"^[a-z][a-z0-9_.-]{0,49}$")
_UUID_SEGMENT = re.compile(
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_LONG_NUMBER = re.compile(r"/\d{4,}")


def _label(value: str, *, fallback: str = "other") -> str:
    value = str(value or "").strip()
    return value if _SAFE_VALUE.fullmatch(value) else fallback


def normalize_route(route: str) -> str:
    """Normalize a route/template without retaining resource identifiers."""

    value = _UUID_SEGMENT.sub("/:id", str(route or "").strip())
    value = _LONG_NUMBER.sub("/:id", value)
    value = re.sub(r"/[A-Za-z0-9_-]{24,}(?=/|$)", "/:id", value)
    if len(value) > 120:
        value = value[:120]
    return _label(value or "unknown_route", fallback="unknown_route")


class _Histogram:
    def __init__(self) -> None:
        self.buckets = [0 for _ in _BUCKETS]
        self.inf = 0
        self.total = 0.0
        self.count = 0

    def observe(self, value: float) -> None:
        value = max(float(value), 0.0)
        for index, bucket in enumerate(_BUCKETS):
            if value <= bucket:
                self.buckets[index] += 1
        self.inf += 1
        self.total += value
        self.count += 1


class MetricsRegistry:
    """Thread-safe counters/histograms with a fixed low-cardinality schema."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._counters: dict[str, dict[tuple[tuple[str, str], ...], int]] = defaultdict(dict)
        self._histograms: dict[str, dict[tuple[tuple[str, str], ...], _Histogram]] = defaultdict(dict)
        self._gauges: dict[str, float] = {"careercrew_upload_backlog": 0.0}

    @staticmethod
    def _key(**labels: str) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((name, _label(value)) for name, value in labels.items()))

    def _inc(self, name: str, key: tuple[tuple[str, str], ...], amount: int = 1) -> None:
        values = self._counters[name]
        values[key] = values.get(key, 0) + int(amount)

    def _observe(self, name: str, key: tuple[tuple[str, str], ...], value: float) -> None:
        histogram = self._histograms[name].setdefault(key, _Histogram())
        histogram.observe(value)

    def observe_http(self, method: str, route: str, status_code: int, duration_seconds: float) -> None:
        method = str(method or "other").upper()
        method = method if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} else "OTHER"
        route = normalize_route(route)
        status = f"{int(status_code) // 100}xx" if int(status_code) >= 100 else "unknown"
        key = self._key(method=method, route=route, status=status)
        with self._lock:
            self._inc("careercrew_http_requests_total", key)
            self._observe("careercrew_http_request_duration_seconds", self._key(method=method, route=route), duration_seconds)

    def observe_llm(
        self,
        module: str,
        status: str,
        duration_seconds: float,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        del input_tokens, output_tokens
        module = module if _MODULE_VALUE.fullmatch(str(module or "")) else "other"
        status = status if str(status) in {"completed", "failed", "cancelled", "rejected"} else "other"
        key = self._key(module=module, status=status)
        with self._lock:
            self._inc("careercrew_llm_requests_total", key)
            self._observe("careercrew_llm_request_duration_seconds", self._key(module=module), duration_seconds)

    def inc_rag(self, operation: str) -> None:
        operation = operation if operation in {"query", "hit", "miss", "error"} else "other"
        with self._lock:
            self._inc("careercrew_rag_operations_total", self._key(operation=operation))

    def inc_upload(self, status: str) -> None:
        status = status if status in {"queued", "running", "done", "error", "backlog"} else "other"
        with self._lock:
            self._inc("careercrew_upload_tasks_total", self._key(status=status))

    def inc_tool(self, status: str) -> None:
        status = status if status in {"completed", "failed", "awaiting_confirmation", "error"} else "other"
        with self._lock:
            self._inc("careercrew_tool_calls_total", self._key(status=status))

    def inc_sse_interrupted(self) -> None:
        with self._lock:
            self._inc("careercrew_sse_interrupted_total", ())

    def set_upload_backlog(self, value: int) -> None:
        with self._lock:
            self._gauges["careercrew_upload_backlog"] = max(int(value), 0)

    @staticmethod
    def _format_labels(labels: Iterable[tuple[str, str]]) -> str:
        pairs = []
        for name, value in labels:
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            pairs.append(f'{name}="{escaped}"')
        return "{" + ",".join(pairs) + "}" if pairs else ""

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name in sorted(self._counters):
                lines.append(f"# TYPE {name} counter")
                for labels, value in sorted(self._counters[name].items()):
                    lines.append(f"{name}{self._format_labels(labels)} {value}")
            for name in sorted(self._histograms):
                lines.append(f"# TYPE {name} histogram")
                for labels, histogram in sorted(self._histograms[name].items()):
                    for bucket, count in zip(_BUCKETS, histogram.buckets, strict=True):
                        bucket_labels = tuple(labels) + (("le", _format_bucket(bucket)),)
                        lines.append(f"{name}_bucket{self._format_labels(bucket_labels)} {count}")
                    inf_labels = tuple(labels) + (("le", "+Inf"),)
                    lines.append(f"{name}_bucket{self._format_labels(inf_labels)} {histogram.inf}")
                    lines.append(f"{name}_sum{self._format_labels(labels)} {histogram.total:.9g}")
                    lines.append(f"{name}_count{self._format_labels(labels)} {histogram.count}")
            for name, value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {value:g}")
        return "\n".join(lines) + "\n"


def _format_bucket(value: float) -> str:
    return f"{value:g}"


_registry = MetricsRegistry()


def get_metrics_registry() -> MetricsRegistry:
    return _registry


__all__ = ["MetricsRegistry", "get_metrics_registry", "normalize_route"]
