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

# 每班人数上限：只作为「拆几个班」的上界，实际按学院人数均分
_STUDENTS_PER_CLASS = 30
# 每个学院固定班数（教师端班级概览按学院看，班数一致才好对比）
_CLASSES_PER_COLLEGE = 5

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

    # 3. 分配 500 学生的**学院**
    #
    # 为什么先定学院、再定专业：分班是按「学院+年级」走的，如果先随机分专业
    # 再由专业反推学院，各学院人数就会漂移 —— 物流工程学院只有 4 个专业、
    # 抽样期望才 30 人/年级，实际跑出来 WL2301 只有 2 人，教师端出现「2 人班」。
    # 所以这里改成**学院人数预算固定、专业在学院内二次分配**，保证每学院
    # 每班人数落在可演示区间（≥8 人）。
    #
    # 预算依据：软件学院/讯飞人工智能学院各 3/5 个专业，是本校重点，
    # 4 个重点专业（软工、大数据、信管、人工智能）落在这两家，给足人数。
    _COLLEGE_BUDGET = {
        "讯飞人工智能学院": 145,
        "软件学院": 118,
        "会计学院": 58,
        "金融学院": 52,
        "经济学院": 42,
        "新媒体艺术学院": 34,
        "公共管理学院": 28,
        "物流工程学院（国际商学院）": 23,
    }
    assert sum(_COLLEGE_BUDGET.values()) == _TOTAL_STUDENTS, "学院人数预算必须正好 500"

    # 每个专业的配额：重点专业先占，剩下的名额在学院内其余专业间轮转分配
    college_majors: dict[str, list[str]] = {}
    for m, (col, _, _) in school_cqufe.MAJORS.items():
        college_majors.setdefault(col, []).append(m)

    major_quota: dict[str, int] = {m: 0 for m in school_cqufe.MAJORS}
    for col, budget in _COLLEGE_BUDGET.items():
        mj = sorted(college_majors[col])
        key_here = [m for m in _KEY_MAJORS if m in mj]
        others = [m for m in mj if m not in _KEY_MAJORS]
        # 重点专业保底 _KEY_PER_MAJOR，不够则整体均分
        base = {m: _KEY_PER_MAJOR for m in key_here}
        left = budget - sum(base.values())
        if left < 0:  # 预算比保底还小，改成学院内均分
            base = {}
            left = budget
        pool = others if others else mj
        i = 0
        while left > 0:
            m = pool[i % len(pool)]
            base[m] = base.get(m, 0) + 1
            left -= 1
            i += 1
        for m, q in base.items():
            major_quota[m] = q

    assert sum(major_quota.values()) == _TOTAL_STUDENTS
    major_list: list[str] = []
    for m, q in major_quota.items():
        major_list.extend([m] * q)
    rng.shuffle(major_list)

    # 4. 生成学生数据
    # ----------------------------------------------------------------
    # 分班规则：**同学院 + 同年级 编一（或若干）班，人数尽量均分**。
    #
    # 为什么按「学院+年级」而不是「学院+年级+专业」：
    # 500 人摊到 32 专业 × 4 年级 = 117 个组合，平均每组才 4 人，
    # 按专业分班必然出现「1 人班」，教师端班级概览、预警列表、班级差距
    # 全都只有一条数据，等于没法演示。按学院+年级分班后每班 8-28 人，
    # 班级内跨专业也很正常（真实院校的行政班也常是同学院多专业混合）。
    # 每个学生的 major 字段仍然准确，专业维度统计不受影响。
    # ----------------------------------------------------------------
    students: list[dict] = []
    hidden_risk_records: list[tuple[str, bool]] = []

    n_risk = 0
    n_fail = 0

    # 年级按学院内轮转分配，而不是 rng.choice —— 随机抽样会让某个年级
    # 偶然只剩 1-2 人（上一版 WL2301=2 人就是这么来的）。轮转 = 各年级人数
    # 相差不超过 1，班级人数才对得上。
    skeleton: list[dict] = []
    by_college: dict[str, list[str]] = {}
    for major in major_list:
        by_college.setdefault(school_cqufe.MAJORS[major][0], []).append(major)
    for college, majors in by_college.items():
        # 学院内打散专业顺序，避免「同年级 = 同一批专业」的整齐感
        rng.shuffle(majors)
        for i, major in enumerate(majors):
            skeleton.append({
                "college": college,
                "major": major,
                "grade": _GRADES[i % len(_GRADES)],
            })

    # 分班：**每个学院固定 _CLASSES_PER_COLLEGE 个班**（8 学院 × 5 = 40 班）。
    #
    # 分法：整个学院的人按学院总人数均分成 5 份，每份一个行政班。
    # 为什么不再按「学院+年级」切：一个学院每个年级才十几人，
    # 按年级切每级只能凑出 1 个班（4 个年级 = 4 个班，永远到不了 5），
    # 而且 RJ 这种大院子会冒出 8 个班。改成学院整体均分 5 份后，
    # 每个学院都是 5 个班、人数接近，教师端下拉框整齐。
    #
    # 班号：`{学院缩写}{主力年级后两位}{01..05}`。主力年级 = 该班人最多的年级，
    # 这样「RJ2401」能读出「软件学院 24 级 1 班」，符合真实习惯；
    # 同一个学院 5 个班的主力年级不同时也不会撞号（见下方 _unique_class_name）。
    def _split_sizes(n: int, k: int) -> list[int]:
        """把 n 人尽量平均地拆成 k 个班。"""
        if n <= 0:
            return []
        k = max(1, min(k, n))
        base, extra = divmod(n, k)
        return [base + (1 if i < extra else 0) for i in range(k)]

    # 学号在同一学院内按年级连续编号（同学院多专业共享号段，符合真实学籍规则）
    student_seq: dict[tuple[str, int], int] = {}
    by_college_rows: dict[str, list[dict]] = {}
    for row in skeleton:
        by_college_rows.setdefault(row["college"], []).append(row)

    for college in sorted(by_college_rows):
        rows = by_college_rows[college]
        abbr = _COLLEGE_ABBR[college]
        k = min(_CLASSES_PER_COLLEGE, len(rows))
        sizes = _split_sizes(len(rows), k)

        # 先按年级排序再切，同一个年级的人会连续落在相邻班里 → 主力年级稳定，
        # 班号读起来像「KJ2201 KJ2202 ... KJ2205」，而不是 2201/2505/2302 乱跳。
        rows = sorted(rows, key=lambda r: (r["grade"], r["major"]))

        cursor = 0
        used_names: set[str] = set()
        for idx, size in enumerate(sizes, 1):
            members = rows[cursor:cursor + size]
            cursor += size
            if not members:
                continue
            # 主力年级：该班出现次数最多的年级
            main_grade = Counter(r["grade"] for r in members).most_common(1)[0][0]
            yy = str(main_grade)[-2:]
            class_name = f"{abbr}{yy}{idx:02d}"
            # 同学院内避免重名（主力年级不同也可能撞号）
            if class_name in used_names:
                class_name = f"{abbr}{yy}{idx + 50:02d}"
            used_names.add(class_name)

            for r in members:
                r["class_name"] = class_name
                key = (college, r["grade"])
                student_seq[key] = student_seq.get(key, 0) + 1
                r["student_no"] = f"{abbr}{r['grade']}{student_seq[key]:03d}"

    for row in skeleton:
        college, major, grade = row["college"], row["major"], row["grade"]
        student_no = row["student_no"]

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
            "class_name": row["class_name"],
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
        # career_intent 也按 student_id 关联；不清会让重灌后的新学号继承旧目标
        for t in ["score", "attendance", "student", "course", "career_intent"]:
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
