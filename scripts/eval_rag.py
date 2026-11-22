# scripts/eval_rag.py
# 职责：RAG 检索效果离线评测——同一批真实知识库分块上，对比 rag-v1 与 rag-v2 的命中率。
# 依赖：MySQL（只读 `知识库分块`/`知识库文档`）、sklearn、engine.rag
# 用法：python scripts/eval_rag.py            # 全量题集
#       python scripts/eval_rag.py -v         # 附带每题检索到的标题
#
# 说明：v1 的公式在这里**原样复刻**（0.7×余弦 + 0.3×集合覆盖），
#       不改动线上代码即可拿到可比基线；v2 直接调 engine.rag.search。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine import rag  # noqa: E402

# ---- 题集：问题 + 期望命中的文档标题关键字（任一命中即算对）----------------
CASES: list[tuple[str, tuple[str, ...]]] = [
    ("我挂了两门课会不会被预警，学院会怎么帮我", ("学业预警", "课程考核", "学籍与学分")),
    ("补考没过还能重修吗", ("课程考核", "学业预警")),
    ("奖学金什么时候评，国家奖学金多少钱", ("奖学金",)),
    ("助学贷款怎么申请，需要准备哪些材料", ("助学贷款",)),
    ("三方协议签了想违约要赔多少钱", ("就业协议", "就业指导")),
    ("实习期间出了安全事故谁负责", ("实习安全", "实习实践")),
    ("想转专业需要满足什么条件", ("转专业",)),
    ("宿舍晚上几点关门，晚归怎么办", ("宿舍",)),
    ("对学校的处分不服可以怎么申诉", ("申诉",)),
    ("请假超过三天要找谁审批", ("请假", "考勤")),
    ("数据分析师岗位需要掌握哪些工具和技能", ("数据分析师",)),
    ("Java 后端开发工程师的岗位职责是什么", ("Java",)),
    ("家庭经济困难认定要提交哪些证明材料", ("家庭经济困难",)),
    ("考试作弊会被怎么处理", ("考试纪律", "违纪")),
    ("创新创业学分怎么获得", ("创新创业", "学科竞赛")),
    ("职业资格证书能不能抵学分", ("职业资格",)),
    ("休学一年以后怎么复学", ("休学",)),
    ("就业指导中心能提供哪些服务", ("就业指导",)),
    ("国家助学贷款的利息怎么算", ("助学贷款",)),
    ("软件测试工程师的任职要求", ("软件测试",)),
    ("产品经理这个岗位平时做什么", ("产品经理",)),
    ("新媒体运营需要什么能力", ("新媒体运营",)),
    ("会计岗位的职责和任职资格", ("会计",)),
    ("审计助理岗位要求", ("审计助理",)),
    ("银行客户经理的考核指标", ("银行客户经理",)),
    ("人力资源专员负责哪些模块", ("人力资源专员",)),
    ("供应链专员岗位职责", ("供应链专员",)),
    ("机械设计工程师需要什么专业技能", ("机械设计",)),
    ("法务专员岗位要求", ("法务",)),
    ("公务员综合管理类岗位主要做什么", ("公务员",)),
    ("学籍异动需要办哪些手续", ("学籍与学分", "转专业")),
    ("课程考核不及格怎么补考重修", ("课程考核",)),
    ("实践学分怎么认定", ("实习实践", "职业资格")),
    ("考试的时候手机响了算违纪吗", ("考试纪律", "违纪")),
    # 反例组：这些确实只写在《学生手册》里。
    # 用来盯住「文档体量先验」别把汇编一棍子打死——加了先验后这几题仍必须命中手册。
    ("校园卡丢了怎么补办", ("学生手册",)),
    ("医保怎么报销，校医院能直接刷吗", ("学生手册",)),
    ("图书馆借的书超期要罚款吗", ("学生手册",)),
    ("体育课可以申请免修吗", ("学生手册",)),
    ("心理咨询怎么预约", ("学生手册",)),
    ("宿舍能用电吹风吗", ("宿舍", "学生手册")),
]


def _rows() -> list[dict]:
    import os

    import pymysql
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"), port=int(os.getenv("MYSQL_PORT", 3306)),
        user=os.getenv("MYSQL_USER", "root"), password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DB", "qihang"), charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.`文档编号` doc_id, d.`标题` title, c.`块号` chunk_no, "
                "c.`页码` page, c.`文本` text "
                "FROM `知识库分块` c JOIN `知识库文档` d ON d.`编号` = c.`文档编号` "
                "WHERE d.`状态` = 'ready'")
            return list(cur.fetchall())
    finally:
        conn.close()


# v1 出厂时的口语扩展表（11 组）。基线必须用这一份，不能共用 v2 的新表，
# 否则「基线」会白拿 v2 的收益，对比就失真了。
_V1_EXPANSIONS: tuple[tuple[str, str], ...] = (
    ("挂科", "不及格 补考 重修 成绩 学业预警"),
    ("补考", "补考 重修 不及格 成绩"),
    ("没过", "不及格 补考 重修 成绩"),
    ("重修", "重修 补考 不及格"),
    ("毕业", "毕业学分 学籍 毕业资格 培养方案"),
    ("退学", "退学 休学 学籍 学业警示"),
    ("休学", "休学 复学 学籍"),
    ("奖学金", "奖学金 助学金 评定 国家奖学金"),
    ("助学贷款", "助学贷款 贷款 还款 征信"),
    ("三方协议", "就业协议 违约金 档案 报到证"),
    ("实习", "实习 实践 学分 安全"),
)


def _v1_expand(query: str) -> str:
    extra = [expansion for word, expansion in _V1_EXPANSIONS if word in query]
    return f"{query} {' '.join(extra)}" if extra else query


def _v1_search(query: str, rows: list[dict], top_k: int = 4) -> list[dict]:
    """rag-v1 打分原样复刻：0.7×余弦 + 0.3×集合覆盖。"""
    items, vectorizer, matrix, norm_texts, _idf, _sizes = rag.build_index(rows)
    qv = vectorizer.transform([_v1_expand(query)])
    sims = (matrix @ qv.T).toarray().ravel()
    q_norm = rag._norm(query)                      # noqa: SLF001 - 复刻基线需要内部归一化
    q_grams = {q_norm[j:j + 2] for j in range(max(1, len(q_norm) - 1))}
    hits = []
    for i, it in enumerate(items):
        cos = float(sims[i])
        if cos <= 0:
            continue
        block = norm_texts[i]
        covered = [g for g in q_grams if g and g in block]
        coverage = len(covered) / max(1, len(q_grams))
        score = 0.7 * cos + 0.3 * coverage
        if score < 0.03:
            continue
        hits.append({"doc_id": it.doc_id, "title": it.title, "chunk_no": it.chunk_no,
                     "text": it.text, "score": round(score, 6)})
    hits.sort(key=lambda h: (-h["score"], h["doc_id"], h["chunk_no"]))
    if hits:
        floor = hits[0]["score"] * 0.45
        hits = [h for h in hits if h["score"] >= floor]
    return hits[:top_k]


def _hit(hits: list[dict], expects: tuple[str, ...]) -> tuple[bool, int | None]:
    for rank, hit in enumerate(hits, start=1):
        if any(word in str(hit["title"]) for word in expects):
            return True, rank
    return False, None


def main() -> int:
    verbose = "-v" in sys.argv
    rows = _rows()
    print(f"语料：{len({r['doc_id'] for r in rows})} 篇文档 / {len(rows)} 块\n")
    print(f"{'#':>2}  {'v1':<12}{'v2':<12}问题")
    stat = {"v1@1": 0, "v1@3": 0, "v2@1": 0, "v2@3": 0, "n": 0}
    for index, (query, expects) in enumerate(CASES, start=1):
        v1 = _v1_search(query, rows)
        v2 = rag.search(query, rows, top_k=4)
        ok1, rank1 = _hit(v1, expects)
        ok2, rank2 = _hit(v2, expects)
        stat["n"] += 1
        stat["v1@1"] += 1 if rank1 == 1 else 0
        stat["v1@3"] += 1 if ok1 else 0
        stat["v2@1"] += 1 if rank2 == 1 else 0
        stat["v2@3"] += 1 if ok2 else 0
        m1 = "✓ 第1" if rank1 == 1 else (f"✓ 第{rank1}" if ok1 else "✗")
        m2 = "✓ 第1" if rank2 == 1 else (f"✓ 第{rank2}" if ok2 else "✗")
        print(f"{index:>2}  {m1:<12}{m2:<12}{query}")
        if verbose:
            for tag, got in (("v1", v1), ("v2", v2)):
                titles = [f"{h['title'][:14]}({h['score']:.3f})" for h in got[:3]]
                print(f"      {tag}: {' | '.join(titles)}")
    n = stat["n"]
    print("\n" + "=" * 62)
    print(f"命中率 @1   v1 {stat['v1@1']}/{n} = {stat['v1@1'] / n:.1%}   "
          f"v2 {stat['v2@1']}/{n} = {stat['v2@1'] / n:.1%}")
    print(f"命中率 @3   v1 {stat['v1@3']}/{n} = {stat['v1@3'] / n:.1%}   "
          f"v2 {stat['v2@3']}/{n} = {stat['v2@3'] / n:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
