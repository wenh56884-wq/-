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
# 学生规模：1 万人。班级/学院数量固定不变（8 学院 × 5 班 = 40 班），
# 所以每班约 250 人 —— 这个量级是刻意选的：教师端班级概览、预警列表、
# 班级差距都要在「几百条记录」下才看出性能表现，40 人的演示数据压力不够。
_TOTAL_STUDENTS = 10_000
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

_COURSES_PER_TERM = 6

# 年级 ↔ 入学年份：2026 级=大一，2025 级=大二，2024 级=大三，2023 级=大四。
# 注意这里的「年级编号」是**级**（入学届别），学号/班级号里的年份段就用它
# （如 KJ20230001 / KJ2301 就是 2023 级 = 大四）。
_GRADE_LABEL = {2026: "大一", 2025: "大二", 2024: "大三", 2023: "大四"}
_GRADES = [2023, 2024, 2025, 2026]  # 大四 / 大三 / 大二 / 大一（按入学届别）

# 当前学年：数据快照截在 2025-2026 学年第 2 学期。
# 「当前学年起始年」= 2025，因此 2026 级是这一学年刚入学的大一。
_CUR_ACADEMIC_START = 2025
_CUR_TERM_INDEX = 2  # 1=上学期，2=下学期（当前）


def _grade_of(enroll_year: int) -> int:
    """届别 → 年级序号（1=大一 … 4=大四）。

    届别数字越大、年级越低：2026 级刚入学=大一(1)，2023 级=大四(4)。
    即 grade_no = 1 + (最新届别 - enroll_year)，最新届别 = 当前学年起始年 + 1。
    """
    newest = _CUR_ACADEMIC_START + 1  # 当前学年入学的届别，即大一
    return 1 + (newest - enroll_year)


def _terms_for_grade(enroll_year: int) -> list[str]:
    """某届学生在校期间**至今**应修的学期列表（按时间升序）。

    从入学那年的上学期起，一直排到当前学期（2025-2026-2）。于是：
      2026 级（大一）→ 2 个学期（2025-2026-1、-2）
      2025 级（大二）→ 4 个学期（2024-2025-1 ~ 2025-2026-2）
      2024 级（大三）→ 6 个学期（2023-2024-1 ~ 2025-2026-2）
      2023 级（大四）→ 8 个学期（2022-2023-1 ~ 2025-2026-2）
    「大四要有大一、大二、大三的成绩」正是这个累积序列的副产品。
    """
    grade_no = _grade_of(enroll_year)
    first_academic = _CUR_ACADEMIC_START - (grade_no - 1)
    terms: list[str] = []
    for year in range(first_academic, _CUR_ACADEMIC_START + 1):
        for half in (1, 2):
            if year == _CUR_ACADEMIC_START and half > _CUR_TERM_INDEX:
                break
            terms.append(f"{year}-{year + 1}-{half}")
    return terms


# 当前学期（画像/推荐都看它）
_TERM = f"{_CUR_ACADEMIC_START}-{_CUR_ACADEMIC_START + 1}-{_CUR_TERM_INDEX}"

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

    # 3. 分配 1 万学生的**学院**
    #
    # 为什么先定学院、再定专业：分班是按「学院+年级」走的，如果先随机分专业
    # 再由专业反推学院，各学院人数就会漂移 —— 物流工程学院只有 4 个专业、
    # 抽样期望不够，实际跑出来会出现「2 人班」。所以改成**学院人数预算固定、
    # 专业在学院内二次分配**，保证每学院每班人数均匀可控。
    #
    # 预算依据：参考本校实际在校生结构 —— 讯飞人工智能学院、软件学院是重点
    # （IT 侧，5/3 个专业），会计/金融/经济属财经主体（各 4 个专业），
    # 新媒体/公管/物流偏小。
    _COLLEGE_BUDGET = {
        "讯飞人工智能学院": 2900,
        "软件学院": 2350,
        "会计学院": 1150,
        "金融学院": 1050,
        "经济学院": 850,
        "新媒体艺术学院": 680,
        "公共管理学院": 560,
        "物流工程学院（国际商学院）": 460,
    }
    assert sum(_COLLEGE_BUDGET.values()) == _TOTAL_STUDENTS, (
        f"学院人数预算必须正好 {_TOTAL_STUDENTS}"
    )

    # 每个专业的配额：学院预算在**学院内各专业间均分**，重点专业上浮权重。
    #
    # 1 万人规模下不能再写「每专业保底 32 人」那种绝对数——会和学院预算脱节。
    # 改成按权重切：重点专业权重 1.4（软件工程/大数据/人工智能/会计/金融等
    # 就业面广的专业人多一点），其余 1.0。零头按权重从高到低逐个补齐，
    # 保证每个专业配额之和恰好等于学院预算。
    _KEY_WEIGHT = 1.4
    college_majors: dict[str, list[str]] = {}
    for m, (col, _, _) in school_cqufe.MAJORS.items():
        college_majors.setdefault(col, []).append(m)

    major_quota: dict[str, int] = {m: 0 for m in school_cqufe.MAJORS}
    for col, budget in _COLLEGE_BUDGET.items():
        mj = sorted(college_majors[col])
        weights = [(_KEY_WEIGHT if m in _KEY_MAJORS else 1.0) for m in mj]
        wsum = sum(weights)
        raw = [budget * w / wsum for w in weights]
        quota = [int(x) for x in raw]
        # 零头按小数部分从大到小补，直到分完（确定性、可复现）
        remainder = budget - sum(quota)
        order = sorted(range(len(mj)), key=lambda i: (-(raw[i] - quota[i]), mj[i]))
        for i in order[:remainder]:
            quota[i] += 1
        for m, q in zip(mj, quota):
            major_quota[m] = q

    assert sum(major_quota.values()) == _TOTAL_STUDENTS, (
        f"专业配额之和 {sum(major_quota.values())} 应等于 {_TOTAL_STUDENTS}"
    )
    major_list: list[str] = []
    for m, q in major_quota.items():
        major_list.extend([m] * q)
    rng.shuffle(major_list)

    # 4. 生成学生数据
    # ----------------------------------------------------------------
    # 分班规则：**每个学院 5 个班，5 个班按年级拆分**，班内再均分人数。
    #
    # 1 万人 / 40 班 = 每班约 250 人。这个规模下必须让班**有年级归属**：
    # 一个 250 人的班里混着大一到大四，教师端看班级画像、预警、职业目标
    # 都没法解释（大一还没成绩、大四已经在找工作）。
    #
    # 具体切法：5 个班先按年级分（大四/大三/大二/大一 各 1 个），第 5 个班
    # 给人数最多的年级做个「平行班」。所以每个学院的班级构成是
    # 「每个年级至少 1 个班 + 主力年级多 1 个」，班号 `{缩写}{年级后两位}{序号}`。
    # 例如软件学院：RJ2201 RJ2301 RJ2401 RJ2501 RJ2402。
    #
    # 每个学生的 major 字段仍然准确，专业维度统计不受影响。
    # ----------------------------------------------------------------
    students: list[dict] = []
    hidden_risk_records: list[tuple[str, bool]] = []

    n_risk = 0
    n_fail = 0

    def _split_sizes(n: int, k: int) -> list[int]:
        """把 n 人尽量平均地拆成 k 份。"""
        if n <= 0:
            return []
        k = max(1, min(k, n))
        base, extra = divmod(n, k)
        return [base + (1 if i < extra else 0) for i in range(k)]

    # 先按学院把 1 万人分组（每个元素 = 一个学生占位）
    skeleton: list[dict] = []
    by_college: dict[str, list[str]] = {}
    for major in major_list:
        by_college.setdefault(school_cqufe.MAJORS[major][0], []).append(major)

    # 学号在同一学院内按**年级**连续编号（同学院多专业共享号段，符合真实学籍规则）
    student_seq: dict[tuple[str, int], int] = {}
    class_report: list[dict] = []

    for college in sorted(by_college):
        abbr = _COLLEGE_ABBR[college]
        majors = by_college[college]  # 长度 = 该学院学生总数
        rng.shuffle(majors)           # 打散专业顺序，避免「同年级=同一批专业」的整齐感

        # ① 每个学生挂年级：按学院人数均分成 4 段（各年级人数差 ≤1）
        grade_sizes = _split_sizes(len(majors), len(_GRADES))
        grade_pool: dict[int, list[str]] = {}
        cursor = 0
        for grade, size in zip(_GRADES, grade_sizes):
            grade_pool[grade] = majors[cursor:cursor + size]
            cursor += size

        # ② 4 个年级各 1 个班，第 5 个班是**混合班**（各年级按人数比例抽）。
        #
        # 为什么这样切：学院 5 个班、4 个年级，最自然的读法是「每级 1 个班 +
        # 1 个混合班」。前 4 个班班号干净（KJ2201 / KJ2301 / KJ2401 / KJ2501），
        # 第 5 个班叫 `{缩写}MX01`（MX = 混合），教师端一眼能看出它的性质。
        #
        # 每班人数：先扣掉混合班的分额，剩下的按年级人数比例分。
        # 为让 5 个班人数接近，混合班每个年级抽走「该年级比例」的人。
        n_college = sum(len(grade_pool[g]) for g in _GRADES)
        # 混合班目标人数 ≈ 学院人数 / 5，按年级人数占比拆分
        mix_target = n_college // _CLASSES_PER_COLLEGE
        mix_taken: dict[int, int] = {}
        remaining = mix_target
        # 从人数最多的年级开始抽，避免把小学院抽空
        for grade in sorted(_GRADES, key=lambda g: (-len(grade_pool[g]), g)):
            take = round(mix_target * len(grade_pool[grade]) / n_college)
            take = min(take, max(0, len(grade_pool[grade]) - 1))  # 至少给本年级留 1 人
            mix_taken[grade] = take
            remaining -= take
        # 零头补给人数最多的年级
        if remaining != 0:
            top = max(_GRADES, key=lambda g: len(grade_pool[g]))
            mix_taken[top] = min(
                mix_taken[top] + remaining, max(0, len(grade_pool[top]) - 1)
            )

        mix_members: list[tuple[str, int]] = []
        for grade in _GRADES:
            take = mix_taken[grade]
            mix_members.extend((m, grade) for m in grade_pool[grade][:take])
            grade_pool[grade] = grade_pool[grade][take:]

        # ③ 每级 1 个班，班号 = 缩写 + 年级后两位 + 01
        for grade in _GRADES:
            members = grade_pool[grade]
            if not members:
                continue
            class_name = f"{abbr}{str(grade)[-2:]}01"
            for major in members:
                student_seq[(college, grade)] = student_seq.get((college, grade), 0) + 1
                skeleton.append({
                    "college": college,
                    "major": major,
                    "grade": grade,
                    "class_name": class_name,
                    "student_no": f"{abbr}{grade}{student_seq[(college, grade)]:04d}",
                })
            class_report.append({
                "class_name": class_name,
                "college": college,
                "grade": grade,
                "headcount": len(members),
                "grade_mix": {grade: len(members)},
            })

        # ④ 混合班
        if mix_members:
            class_name = f"{abbr}MX01"
            for major, grade in mix_members:
                student_seq[(college, grade)] = student_seq.get((college, grade), 0) + 1
                skeleton.append({
                    "college": college,
                    "major": major,
                    "grade": grade,
                    "class_name": class_name,
                    "student_no": f"{abbr}{grade}{student_seq[(college, grade)]:04d}",
                })
            gm = Counter(g for _, g in mix_members)
            class_report.append({
                "class_name": class_name,
                "college": college,
                "grade": max(gm, key=lambda g: gm[g]),
                "headcount": len(mix_members),
                "grade_mix": dict(gm),
            })

    assert len(skeleton) == _TOTAL_STUDENTS, (
        f"分班后人数 {len(skeleton)} 应等于 {_TOTAL_STUDENTS}"
    )

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
        # career_intent 按 student_id 关联；teacher_class/class_warning_threshold
        # 按 class_name 关联；重灌班级结构后不清会留下失效的任教范围/阈值
        for t in ["成绩", "考勤", "学生", "课程",
                  "职业意向", "教师任教班级", "班级预警阈值"]:
            cur.execute(f"TRUNCATE TABLE `{t}`")
        cur.execute("SET FOREIGN_KEY_CHECKS=1")
        # 重置 tenant 种子
        cur.execute(
            "INSERT INTO `租户` (`编号`, `名称`) VALUES (1, '重庆财经学院') "
            "ON DUPLICATE KEY UPDATE `名称`='重庆财经学院'"
        )

        # 灌入课程
        print("灌入课程...")
        cur.executemany(
            "INSERT INTO `课程` (`课程编号`, `课程名称`, `学分`, `专业`) "
            "VALUES (%s, %s, %s, %s)",
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
            "INSERT INTO `学生` "
            "(`租户编号`, `学号`, `姓名`, `学院`, `专业`, `班级`, `年级`, `入学年份`, `口令摘要`) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            student_insert_data,
        )

        # 取 student_no → id 映射
        cur.execute("SELECT `编号`, `学号` FROM `学生`")
        sno2id = {row[1]: row[0] for row in cur.fetchall()}

        # 取 course code → id 映射
        cur.execute("SELECT `编号`, `课程编号` FROM `课程`")
        code2id = {row[1]: row[0] for row in cur.fetchall()}

        # 生成成绩 + 出勤
        print("生成成绩与出勤...")
        risk_samples: list[dict] = []  # 抽查用，只留前 200 条避免 1 万人下吃内存
        _RISK_SAMPLE_CAP = 200

        def _flush(table: str, cols: str, rows: list[tuple]) -> int:
            """分批 executemany，避免 10 万行一次性塞进单条语句。"""
            if not rows:
                return 0
            ncol = len(cols.split(","))
            sql = f"INSERT INTO {table} ({cols}) VALUES (" + ", ".join(["%s"] * ncol) + ")"
            batch = 5000
            for start in range(0, len(rows), batch):
                cur.executemany(sql, rows[start:start + batch])
            return len(rows)

        SCORE_COLS = "`学生编号`, `课程编号`, `学期`, `分数`, `是否重修`"
        ATT_COLS = "`学生编号`, `学期`, `应到次数`, `缺勤次数`, `出勤率`"

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

            # 该生在校至今应修的学期序列（按年级累积，大四最长）
            terms = _terms_for_grade(int(s["enroll_year"]))
            n_terms = len(terms)

            for term_idx, term in enumerate(terms):
                # 风险学生：**最近一学期**降分（越近越差才是预警信号）
                if s["is_risk"] and term_idx == n_terms - 1:
                    drop = rng.uniform(8, 25)
                    term_mean = base_mean - drop
                elif s["is_risk"] and term_idx >= n_terms - 2:
                    term_mean = base_mean - rng.uniform(2, 10)
                else:
                    term_mean = base_mean + rng.uniform(-3, 5)

                # 随机选 6 门课
                chosen = rng.sample(avail_courses, min(_COURSES_PER_TERM, len(avail_courses)))
                scores = _gen_scores(rng, term_mean)

                # 注入挂科：放在**最近的学期**，否则历史挂科会被后续学期冲淡
                if s["has_fail"] and term_idx == n_terms - 1:
                    # 把至少一门成绩压到 <60
                    fail_idx = rng.randint(0, len(scores) - 1)
                    scores[fail_idx] = rng.uniform(35, 59)

                for (ccode, cname), sc in zip(chosen, scores):
                    cid = code2id[ccode]
                    is_retake = 1 if (sc < 60 and rng.random() < 0.5) else 0
                    score_rows.append((sid, cid, term, round(sc, 2), is_retake))

                # 出勤
                total_sessions = rng.randint(16, 20)
                if s["is_risk"] and term_idx >= n_terms - 2:
                    absent = rng.randint(int(total_sessions * 0.22), int(total_sessions * 0.45))
                else:
                    absent = rng.randint(0, max(1, int(total_sessions * 0.15)))
                rate = round((total_sessions - absent) / total_sessions, 4)
                attendance_rows.append((sid, term, total_sessions, absent, rate))

                # 记录风险学生抽查数据（限量）
                if s["is_risk"] and len(risk_samples) < _RISK_SAMPLE_CAP:
                    risk_samples.append({
                        "student_no": s["student_no"],
                        "name": s["name"],
                        "major": s["major"],
                        "enroll_year": s["enroll_year"],
                        "term": term,
                        "avg_score": round(sum(scores) / len(scores), 2),
                        "attendance_rate": rate,
                    })

        # 批量灌入成绩（分批，1 万人约 9 万行）
        print(f"写入成绩 {len(score_rows)} 行...")
        n_scores = _flush("`成绩`", SCORE_COLS, score_rows)
        score_rows.clear()

        # 批量灌入出勤
        print(f"写入出勤 {len(attendance_rows)} 行...")
        _flush("`考勤`", ATT_COLS, attendance_rows)
        attendance_rows.clear()
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

    # 按年级分布（大一/大二/大三/大四）
    print()
    print("--- 按年级分布 ---")
    by_grade = Counter(s["grade"] for s in students)
    for g in _GRADES:
        cnt = by_grade.get(str(g), 0)
        pct = cnt / len(students) * 100
        terms_n = len(_terms_for_grade(g))
        print(f"  {g}级（{_GRADE_LABEL[g]}）: {cnt} 人（{pct:.1f}%），在校 {terms_n} 个学期")
    print(f"  合计: {sum(by_grade.values())} 人 / {len({s['class_name'] for s in students})} 个班")

    # 班级概览（每个学院 5 个班：每年级 1 班 + 1 个混合班）
    print()
    print(f"--- 班级概览：{len(class_report)} 个班 ---")
    glabel = _GRADE_LABEL
    by_college_cls: dict[str, list[dict]] = {}
    for c in class_report:
        by_college_cls.setdefault(c["college"], []).append(c)
    for college in sorted(by_college_cls):
        rows = sorted(by_college_cls[college], key=lambda x: x["class_name"])
        print(f"  {college}（{len(rows)} 班）")
        for r in rows:
            mix = r["grade_mix"]
            if len(mix) > 1:
                detail = " + ".join(
                    f"{glabel[g]}{n}" for g, n in sorted(mix.items(), reverse=True)
                )
                print(f"    {r['class_name']:<10} {r['headcount']:>4} 人  [混合：{detail}]")
            else:
                print(f"    {r['class_name']:<10} {r['headcount']:>4} 人  {glabel[r['grade']]}")

    # 按专业分布（32 个专业，紧凑每行 4 个）
    print()
    print("--- 按专业分布 ---")
    by_major = Counter(s["major"] for s in students)
    items = sorted(by_major.items(), key=lambda x: -x[1])
    for i in range(0, len(items), 4):
        chunk = items[i:i + 4]
        print("  " + "  ".join(f"{m}:{c}" for m, c in chunk))

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
    # 把同学生多学期数据归组打印（大四会打到 8 个学期）
    for p in picked[:3]:
        sno = p["student_no"]
        terms = {r["term"]: r for r in risk_samples if r["student_no"] == sno}
        print(f"  {sno} {p['name']} ({p['major']}, {_GRADE_LABEL.get(int(p['enroll_year']), '?')})")
        for term in _terms_for_grade(int(p["enroll_year"])):
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
