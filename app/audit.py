# app/audit.py
# 职责：调用审计日志——统一写 agents\tools.write_audit（一处实现，避免两套审计落库逻辑）
# 依赖：agents.tools.write_audit
# 说明：每次请求无论成败都要留痕；审计写失败不得影响主流程（write_audit 内部已兜底）

from __future__ import annotations

import time
from typing import Any, Mapping

from agents.tools import write_audit


def audit_event(
    *,
    actor_type: str,
    actor_id: int | None,
    action: str,
    target: str = "",
    detail: Mapping[str, Any] | None = None,
    duration_ms: float | None = None,
) -> dict[str, Any]:
    """写一条审计；duration_ms 会自动并入 detail，便于统计接口耗时。"""
    payload = {} if detail is None else dict(detail)
    if duration_ms is not None:
        payload["duration_ms"] = round(float(duration_ms), 2)
    return write_audit(
        actor_type=actor_type,
        actor_id=int(actor_id or 0),
        action=action,
        target=target,
        detail=payload,
    )


class RequestTimer:
    """请求计时器：with 代码块结束时给出毫秒耗时。"""

    __slots__ = ("_start",)

    def __enter__(self) -> "RequestTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000.0
