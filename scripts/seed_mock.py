# scripts/seed_mock.py
# 职责：生成 500 名学生模拟数据，灌入 MySQL（student/course/score/attendance）
# 校情来源：etl/school_cqufe.py（唯一来源），运行前先 validate()
# 说明：random.seed(42) 可复现；幂等（先 TRUNCATE）；hidden_risk 真值另存 CSV

from __future__ import annotations

import csv
import hashlib
import random
import sys
from collections import Counter
from pathlib import Path

import pymysql

# 把项目根目录加入 sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings
from etl import school_cqufe

# ----------------------------------------------------------------
# 常量
# ----------------------------------------------------------------
_SEED = 42
_TOTAL_STUDENTS = 500
_TENANT_ID = 1  # 重庆财经学院

# 8 个重点专业各 ≥30 人
_KEY_MAJORS = [
    "软件工程",
    "数据科学与大数据技术",
    "大数据管理与应用",
    "信息管理与信息系统",
    "人工智能",
    "金融学",
    "会计学",
    "财务管理",
]
_KEY_PER_MAJOR = 32  # 8×32=256，其余 244 人分到其余 24 个专业

_TERMS = ["2025-2026-1", "2025-2026-2"]
_COURSES_PER_TERM = 6
_GRADES = [2022, 2023, 2024, 2025]

# 姓名库
_SURNAMES = list("王李张刘陈杨黄赵周吴徐孙朱马胡郭林何高梁郑罗宋谢唐韩冯邓曹彭")
_GIVEN_NAMES_M = ["伟", "强", "磊", "军", "杰", "勇", "涛", "明", "超", "鹏", "辉", "宇", "浩", "飞", "斌", "博"]
_GIVEN_NAMES_F = ["娜", "敏", "静", "丽", "娟", "婷", "雪", "梅", "玲", "燕", "芳", "倩", "颖", "欣", "悦", "雯"]

# 学院缩写映射（用于学号/班级号）
_COLLEGE_ABBR = {
    "会计学院": "KJ",
    "金融学院": "JR",
    "经济学院": "JJ",
    "新媒体艺术学院": "XM",
    "物流工程学院（国际商学院）": "WL",
    "公共管理学院": "GG",
    "软件学院": "RJ",
    "讯飞人工智能学院": "AI",
    "通识教育学院": "TS",
    "马克思主义学院": "MK",
}

# 拼音缩写（课程 code 前缀）——手工映射 32 个专业
_MAJOR_PINYIN = {
    "会计学": "KJ", "财务管理": "CW", "审计学": "SJ", "资产评估": "ZC",
    "金融学": "JR", "信用管理": "XY", "保险学": "BX", "金融科技": "JK",
    "经济学": "JJ", "经济统计学": "JT", "贸易经济": "MY", "数字经济": "SJ2",
    "会展经济与管理": "HZ", "网络与新媒体": "WM", "播音与主持艺术": "BY", "数字媒体艺术": "SM",
    "物流管理": "WL", "电子商务": "DS", "国际经济与贸易": "GM", "供应链管理": "GY",
    "工程管理": "GC", "土地资源管理": "TD", "物业管理": "WY", "健康服务与管理": "JK2",
    "软件工程": "RJ", "信息管理与信息系统": "XX", "大数据管理与应用": "DS2",
    "数据科学与大数据技术": "DS3", "空间信息与数字技术": "KJ2", "智能科学与技术": "ZN",
    "物联网工程": "WLW", "人工智能": "RG",
}

_RISK_RATE = 0.12      # 12% 风险学生
_FAIL_RATE = 0.08      # 8% 挂科
_RISK_FAIL_BONUS = 0.30  # 风险学生额外挂科概率


def _gen_name(rng: random.Random) -> str:
    """随机生成中文姓名。"""
    surname = rng.choice(_SURNAMES)
    if rng.random() < 0.5:
        given = rng.choice(_GIVEN_NAMES_M)
    else:
        given = rng.choice(_GIVEN_NAMES_F)
    return surname + given


def _gen_password_hash(student_no: str) -> str:
    """生成简易密码 hash（演示用，非生产级）。"""
    return hashlib.sha256(f"qihang_{student_no}".encode()).hexdigest()[:32]


def _build_course_catalog() -> list[tuple[str, str, str, str]]:
    """从 school_cqufe.MAJORS 提取全部课程去重，返回 (code, name, credit, major) 列表。"""
    seen: dict[str, str] = {}  # course_name → major（首次出现的专业归属）
    catalog: list[tuple[str, str, str, str]] = []
    for major, (_, _, courses) in school_cqufe.MAJORS.items():
        abbr = _MAJOR_PINYIN[major]
        for idx, course_name in enumerate(courses, 1):
            if course_name not in seen:
                seen[course_name] = major
                code = f"{abbr}{idx:02d}"
                # 学分：3 或 4，按课程名长度粗分
                credit = "4.0" if len(course_name) >= 6 else "3.0"
                catalog.append((code, course_name, credit, major))
    return catalog


def _courses_for_major(major: str, catalog: list[tuple[str, str, str, str]]) -> list[tuple[str, str]]:
    """返回某专业可选课程列表 [(code, name), ...]。"""
    return [(c[0], c[1]) for c in catalog if c[3] == major]


def _gen_scores(rng: random.Random, base_mean: float) -> list[float]:
    """生成 6 门课成绩，正态分布均值 base_mean、标准差 12，裁剪 30~100。"""
    return [max(30.0, min(100.0, rng.gauss(base_mean, 12))) for _ in range(_COURSES_PER_TERM)]


def main() -> None:
    # 1. 校情自检
    errs = school_cqufe.validate()
    if errs:
        print("校情自检失败：")
        for e in errs:
            print(f"  {e}")
        raise SystemExit(1)
    print(f"校情自检通过：{len(school_cqufe.COLLEGES)} 学院，{len(school_cqufe.MAJORS)} 专业")

    rng = random.Random(_SEED)
    settings = get_settings()

    # 2. 构建课程目录
    catalog = _build_course_catalog()
    print(f"课程目录：{len(catalog)} 门（去重后）")

    # 3. 分配 500 学生的专业
    major_list: list[str] = []
    for km in _KEY_MAJORS:
        major_list.extend([km] * _KEY_PER_MAJOR)
    # 其余 244 人分到非重点专业（24 个），均匀抽样
    other_majors = [m for m in school_cqufe.MAJORS if m not in _KEY_MAJORS]
    remaining = _TOTAL_STUDENTS - len(major_list)
    for _ in range(remaining):
        major_list.append(rng.choice(other_majors))
    rng.shuffle(major_list)

    # 4. 生成学生数据
    students: list[dict] = []
    hidden_risk_records: list[tuple[str, bool]] = []
    # 学院→(年级→班序号)
    class_seq: dict[str, dict[int, int]] = {}
    # 学院→(年级→学号序号)
    student_seq: dict[str, dict[int, int]] = {}

    n_risk = 0
    n_fail = 0

    for i in range(_TOTAL_STUDENTS):
        major = major_list[i]
        college = school_cqufe.MAJORS[major][0]
        abbr = _COLLEGE_ABBR[college]
        grade = rng.choice(_GRADES)

        # 班号
        if college not in class_seq:
            class_seq[college] = {}
        gs = class_seq[college]
        gs[grade] = gs.get(grade, 0) + 1
        class_no = gs[grade]
        class_name = f"{abbr}{str(grade)[-2:]}{class_no:02d}"

        # 学号
        if college not in student_seq:
            student_seq[college] = {}
        ss = student_seq[college]
        ss[grade] = ss.get(grade, 0) + 1
        seq_no = ss[grade]
        student_no = f"{abbr}{grade}{seq_no:03d}"

        name = _gen_name(rng)
        enroll_year = grade

        # 风险标记
        is_risk = rng.random() < _RISK_RATE
        if is_risk:
            n_risk += 1

        # 挂科标记
        fail_chance = _FAIL_RATE + (_RISK_FAIL_BONUS if is_risk else 0)
        has_fail = rng.random() < fail_chance
        if has_fail:
            n_fail += 1

        students.append({
            "student_no": student_no,
            "name": name,
            "college": college,
            "major": major,
            "class_name": class_name,
            "grade": str(grade),
            "enroll_year": enroll_year,
            "is_risk": is_risk,
            "has_fail": has_fail,
        })
        hidden_risk_records.append((student_no, is_risk))

    # 5. 生成成绩与出勤
    score_rows: list[tuple] = []
    attendance_rows: list[tuple] = []

    # 需要 student_id，先插入 student 再取 id
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        db=settings.mysql_db,
        charset="utf8mb4",
        autocommit=True,
    )

    try:
        cur = conn.cursor()

        # 幂等：先关外键检查，TRUNCATE 子表，再恢复
        print("清空旧数据（TRUNCATE）...")
        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        for t in ["score", "attendance", "student", "course"]:
            cur.execute(f"TRUNCATE TABLE {t}")
        cur.execute("SET FOREIGN_KEY_CHECKS=1")
        # 重置 tenant 种子
        cur.execute(
            "INSERT INTO tenant (id, name) VALUES (1, '重庆财经学院') "
            "ON DUPLICATE KEY UPDATE name='重庆财经学院'"
        )

        # 灌入课程
        print("灌入课程...")
        cur.executemany(
            "INSERT INTO course (code, name, credit, major) VALUES (%s, %s, %s, %s)",
            catalog,
        )
        n_courses = cur.rowcount

        # 灌入学生
        print("灌入学生...")
        student_insert_data = [
            (_TENANT_ID, s["student_no"], s["name"], s["college"], s["major"],
             s["class_name"], s["grade"], s["enroll_year"], _gen_password_hash(s["student_no"]))
            for s in students
        ]
        cur.executemany(
            "INSERT INTO student "
            "(tenant_id, student_no, name, college, major, class_name, grade, enroll_year, password_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            student_insert_data,
        )

        # 取 student_no → id 映射
        cur.execute("SELECT id, student_no FROM student")
        sno2id = {row[1]: row[0] for row in cur.fetchall()}

        # 取 course code → id 映射
        cur.execute("SELECT id, code FROM course")
        code2id = {row[1]: row[0] for row in cur.fetchall()}

        # 生成成绩 + 出勤
        print("生成成绩与出勤...")
        risk_samples: list[dict] = []  # 抽查用

        for s in students:
            sid = sno2id[s["student_no"]]
            major = s["major"]
            avail_courses = _courses_for_major(major, catalog)
            if len(avail_courses) < _COURSES_PER_TERM:
                # 课程不足 6 门，允许重复采样（理论上不会，每个专业 ≥6 门）
                avail_courses = avail_courses * 2

            # 基础均分
            base_mean = rng.gauss(78, 5)
            base_mean = max(60.0, min(90.0, base_mean))

            for term_idx, term in enumerate(_TERMS):
                # 风险学生第二学期降分
                if s["is_risk"] and term_idx == 1:
                    drop = rng.uniform(8, 25)
                    term_mean = base_mean - drop
                else:
                    term_mean = base_mean + rng.uniform(-3, 5)

                # 随机选 6 门课
                chosen = rng.sample(avail_courses, min(_COURSES_PER_TERM, len(avail_courses)))
                scores = _gen_scores(rng, term_mean)

                # 注入挂科
                if s["has_fail"] and term_idx == 1:
                    # 把至少一门成绩压到 <60
                    fail_idx = rng.randint(0, len(scores) - 1)
                    scores[fail_idx] = rng.uniform(35, 59)

                for (ccode, cname), sc in zip(chosen, scores):
                    cid = code2id[ccode]
                    is_retake = 1 if (sc < 60 and rng.random() < 0.5) else 0
                    score_rows.append((sid, cid, term, round(sc, 2), is_retake))

                # 出勤
                total_sessions = rng.randint(16, 20)
                if s["is_risk"] and term_idx == 1:
                    absent = rng.randint(int(total_sessions * 0.22), int(total_sessions * 0.45))
                else:
                    absent = rng.randint(0, max(1, int(total_sessions * 0.15)))
                rate = round((total_sessions - absent) / total_sessions, 4)
                attendance_rows.append((sid, term, total_sessions, absent, rate))

                # 记录风险学生抽查数据
                if s["is_risk"]:
                    risk_samples.append({
                        "student_no": s["student_no"],
                        "name": s["name"],
                        "major": s["major"],
                        "term": term,
                        "avg_score": round(sum(scores) / len(scores), 2),
                        "attendance_rate": rate,
                    })

        # 批量灌入成绩
        cur.executemany(
            "INSERT INTO score (student_id, course_id, term, score, is_retake) "
            "VALUES (%s, %s, %s, %s, %s)",
            score_rows,
        )
        n_scores = cur.rowcount

        # 批量灌入出勤
        cur.executemany(
            "INSERT INTO attendance (student_id, term, total_sessions, absent_sessions, attendance_rate) "
            "VALUES (%s, %s, %s, %s, %s)",
            attendance_rows,
        )
        conn.commit()

    finally:
        conn.close()

    # 6. 写 hidden_risk.csv
    csv_path = _ROOT / "data" / "hidden_risk.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["student_no", "true_risk"])
        w.writerows([(sno, int(risk)) for sno, risk in hidden_risk_records])
    print(f"hidden_risk.csv 已写出：{len(hidden_risk_records)} 行")

    # 7. 统计打印
    print()
    print("=" * 60)
    print("模拟数据统计")
    print("=" * 60)
    print(f"学生总数：{len(students)}")
    print(f"课程总数：{n_courses}")
    print(f"成绩行数：{n_scores}")
    print(f"挂科人数（含挂科记录）：{n_fail}")
    print(f"风险学生人数：{n_risk}（占比 {n_risk / len(students) * 100:.1f}%）")

    # 按学院分布
    print()
    print("--- 按学院分布 ---")
    by_college = Counter(s["college"] for s in students)
    for college in school_cqufe.COLLEGES:
        cnt = by_college.get(college, 0)
        if cnt > 0:
            print(f"  {college}: {cnt}")

    # 按专业分布
    print()
    print("--- 按专业分布 ---")
    by_major = Counter(s["major"] for s in students)
    for major, cnt in sorted(by_major.items(), key=lambda x: -x[1]):
        print(f"  {major}: {cnt}")

    # 8. 抽查 3 名风险学生
    print()
    print("--- 抽查 3 名风险学生 ---")
    sample3 = rng.sample(risk_samples, min(3, len(risk_samples)))
    # 去重：同一学生只取一次
    seen_sno = set()
    picked = []
    for item in risk_samples:
        if item["student_no"] not in seen_sno:
            seen_sno.add(item["student_no"])
            picked.append(item)
        if len(picked) >= 3:
            break
    # 把同学生两学期数据归组打印
    for p in picked[:3]:
        sno = p["student_no"]
        terms = {r["term"]: r for r in risk_samples if r["student_no"] == sno}
        print(f"  {sno} {p['name']} ({p['major']})")
        for term in _TERMS:
            if term in terms:
                t = terms[term]
                print(f"    {term}: 均分 {t['avg_score']:.2f}, 出勤率 {t['attendance_rate'] * 100:.1f}%")

    # 9. 专业校验
    print()
    major_set = set(s["major"] for s in students)
    known_majors = set(school_cqufe.MAJORS.keys())
    if major_set <= known_majors:
        print("[OK] all student majors are subset of school_cqufe.MAJORS")
    else:
        print("[FAIL] unknown majors:", major_set - known_majors)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
