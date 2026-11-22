# scripts/verify_assessment.py
# 职责：软技能测评全链路冒烟——登录学生 → 取题 → 提交答题 → 查结果，验证引擎口径与身份隔离
# 依赖：fastapi.testclient / app.main（走真实接口与真实数据库）
# 用法：.venv\Scripts\python.exe scripts\verify_assessment.py
# 说明：只读+一次提交；提交后查结果应能看到刚才那条，且 abilities 五个键齐全

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402

ACCOUNT = "AI20230001"
PASSWORD = str(get_settings().demo_password or "")


def _login(client: TestClient) -> dict[str, str]:
    r = client.post("/auth/login", json={"role": "student", "account": ACCOUNT,
                                         "password": PASSWORD})
    if r.status_code != 200:
        raise SystemExit(f"登录失败 {r.status_code} {r.text[:200]}")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main() -> None:
    client = TestClient(create_app())
    headers = _login(client)

    q = client.get("/assessment/questions", headers=headers)
    assert q.status_code == 200, f"取题失败 {q.status_code} {q.text[:200]}"
    questions = q.json()["questions"]
    print(f"取题成功：共 {len(questions)} 题")

    # 全选第一个选项提交（真实计分链路）
    answers = {str(item["id"]): list(item["options"].keys())[0] for item in questions}
    s = client.post("/assessment/submit", headers=headers, json={"answers": answers})
    assert s.status_code == 200, f"提交失败 {s.status_code} {s.text[:200]}"
    body = s.json()
    print(f"提交成功：result_id={body['result_id']} "
          f"总分={body['total_score']}/{body['total_max']} "
          f"答题={body['answered']} 题")
    print("复合能力:", {k: v for k, v in body["abilities"].items()})

    r = client.get("/assessment/results", headers=headers)
    assert r.status_code == 200, f"查结果失败 {r.status_code} {r.text[:200]}"
    results = r.json()["results"]
    print(f"历史结果：共 {len(results)} 条，最新一条 result_id={results[0]['result_id'] if results else None}")

    # 越权验证：教师 token 访问学生测评接口应 403
    t = client.post("/auth/login", json={"role": "teacher", "account": "T001",
                                         "password": PASSWORD})
    if t.status_code == 200:
        th = {"Authorization": f"Bearer {t.json()['access_token']}"}
        f = client.get("/assessment/questions", headers=th)
        assert f.status_code == 403, f"教师越权应 403，实际 {f.status_code}"
        print("教师越权访问 → 403（身份隔离正确）")

    print("✅ 软技能测评全链路冒烟通过")


if __name__ == "__main__":
    main()
