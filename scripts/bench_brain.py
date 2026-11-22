# scripts/bench_brain.py
# 职责：brain 并发执行 vs 串行执行的实际墙钟耗时对比（不连数据库、不调模型）。
# 用法：python scripts/bench_brain.py [单步耗时秒数] [步骤数]
#
# 做法：把 graph._dispatch 换成一个固定 sleep 的假工具，plan/reflect/synthesize
#       全部替换成定值，只保留「执行层」的调度逻辑——这样测出来的就是调度本身。

from __future__ import annotations

import importlib
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.tools import ToolContext  # noqa: E402


def _run(parallel: int, steps: int, delay: float) -> float:
    os.environ["BRAIN_PARALLEL"] = str(parallel)
    os.environ["BRAIN_REFLECT"] = "never"
    os.environ["AGENT_MEMORY_EXTRACT"] = "0"

    from agents import brain, graph  # 延迟导入，保证环境变量先生效

    importlib.reload(brain)

    def fake_dispatch(ctx, name, args):   # noqa: ANN001
        time.sleep(delay)
        return {"items": [{"tool": name}], "total": 1}

    graph._dispatch = fake_dispatch  # noqa: SLF001 - 故意替换，测调度

    planned = [{"tool": f"tool_{i}", "args": {}, "purpose": "压测"}
               for i in range(steps)]
    brain._plan = lambda *a, **k: list(planned)          # noqa: SLF001
    brain._reflect = lambda *a, **k: None               # noqa: SLF001
    brain._synthesize = lambda *a, **k: ("ok", False, {}, 1)  # noqa: SLF001
    brain._extract_memories_async = lambda *a, **k: None      # noqa: SLF001
    brain._ensure_memory_schema = lambda *a, **k: None        # noqa: SLF001
    brain._connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no db"))  # noqa: SLF001

    ctx = ToolContext(actor_type="teacher", tenant_id=1, teacher_id=1)
    started = time.perf_counter()
    result = brain.run_brain(ctx, "压测：同时查三件事")
    elapsed = time.perf_counter() - started
    assert result is not None
    return elapsed


def main() -> int:
    delay = float(sys.argv[1]) if len(sys.argv) > 1 else 1.2
    steps = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    serial = _run(1, steps, delay)
    parallel = _run(3, steps, delay)
    ideal = delay + 0.05
    print(f"假工具单步耗时 {delay:.2f}s × {steps} 步")
    print(f"串行（BRAIN_PARALLEL=1）：{serial:5.2f}s")
    print(f"并发（BRAIN_PARALLEL=3）：{parallel:5.2f}s")
    print(f"加速比：{serial / parallel:.2f}×（理论下限 {ideal:.2f}s，"
          f"即最慢那一步的时间）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
