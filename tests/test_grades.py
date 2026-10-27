# tests/test_grades.py
# 职责：成绩单纯函数聚合——学年/学期分组、多次记录、最高分、学分加权、挂科统计。
# 说明：全部离线，不依赖 MySQL / LLM / 网络。

from __future__ import annotations

from engine.grades import build_report

ROWS = [
    {"record_id": 1, "term": "2022-2023-1", "course_code": "A1", "course_name": "课程A", "credit": 3, "score": 80, "retake": False},
    {"record_id": 2, "term": "2022-2023-1", "course_code": "A1", "course_name": "课程A", "credit": 3, "score": 90, "retake": False},
    {"record_id": 3, "term": "2022-2023-1", "course_code": "B1", "course_name": "课程B", "credit": 4, "score": 50, "retake": False},
    {"record_id": 4, "term": "2022-2023-2", "course_code": "A1", "course_name": "课程A", "credit": 3, "score": 70, "retake": False},
    {"record_id": 5, "term": "2022-2023-2", "course_code": "C1", "course_name": "课程C", "credit": 2, "score": 60, "retake": False},
    {"record_id": 6, "term": "2023-2024-1", "course_code": "D1", "course_name": "课程D", "credit": 3, "score": 55, "retake": True},
]


def test_term_groups_and_best_score():
    report = build_report(ROWS, {"student_no": "S1", "name": "张三"})
    assert report["engine_version"] == "grades-v1"
    assert report["student"]["student_no"] == "S1"
    assert report["summary"]["term_count"] == 3
    assert report["summary"]["year_count"] == 2

    term = report["years"][0]["terms"][0]
    assert term["term"] == "2022-2023-1"
    assert term["term_label"] == "2022-2023 学年 · 第 1 学期"
    a = next(c for c in term["courses"] if c["course_code"] == "A1")
    assert a["score"] == 90.0          # 取最高分
    assert a["latest_score"] == 90.0
    assert a["attempts"] == 2
    assert term["record_count"] == 3
    assert term["course_count"] == 2
    assert term["credits"] == 7.0
    assert term["failed_count"] == 1   # B1 < 60
    assert term["avg_score"] == 70.0   # (90+50)/2
    assert term["weighted_avg"] == 67.14  # (90*3+50*4)/7
    assert [r["attempt"] for r in term["records"] if r["course_code"] == "A1"] == [1, 2]


def test_year_and_summary_dedup_credits():
    report = build_report(ROWS)
    year = report["years"][0]
    assert year["year"] == "2022-2023"
    assert year["course_count"] == 3          # A/B/C 去重
    assert year["credits"] == 9.0             # 3+4+2
    assert year["failed_count"] == 1          # B1
    assert year["record_count"] == 5

    summary = report["summary"]
    assert summary["course_count"] == 4       # A/B/C/D
    assert summary["credits"] == 12.0
    assert summary["failed_count"] == 2       # B1 + D1
    assert summary["record_count"] == 6
    assert summary["avg_score"] == 65.0       # (90+50+70+60+55)/5
    assert summary["weighted_avg"] == 64.33
    assert any("最高分" in n for n in report["notes"])


def test_empty_grades_do_not_fabricate_zero():
    report = build_report([])
    assert report["years"] == []
    assert report["summary"]["avg_score"] is None
    assert report["summary"]["weighted_avg"] is None
    assert report["summary"]["record_count"] == 0
