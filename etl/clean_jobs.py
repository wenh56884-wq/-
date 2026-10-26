# etl/clean_jobs.py
# 职责：清洗 data/raw/ 下 5 个真实招聘 CSV，统一输出 data/cleaned/jobs_cleaned.csv
# 依赖：pandas / re / hashlib / ast / etl.mask
# 说明：纯函数批处理，Boss直聘(2文件) + 前程无忧(3文件) → 统一 schema

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

import pandas as pd

from etl.mask import mask_text

_ROOT = Path(__file__).resolve().parent.parent
_RAW_DIR = _ROOT / "data" / "raw"
_CLEAN_DIR = _ROOT / "data" / "cleaned"

# 输出列
OUTPUT_COLS = [
    "title", "company", "industry", "company_size", "city", "district",
    "salary_min", "salary_max", "salary_unit", "salary_months",
    "exp_min", "exp_max", "education", "skill_tags", "benefits",
    "description", "source", "raw_key",
]

# 学历枚举
_EDU_MAP = {
    "学历不限": "学历不限", "不限": "学历不限", "无": "学历不限",
    "大专": "大专", "专科": "大专",
    "本科": "本科", "大学本科": "本科",
    "硕士": "硕士", "研究生": "硕士",
    "博士": "硕士",  # 稀有，归入硕士
    "在校生/应届生": "学历不限", "应届": "学历不限", "在校应届": "学历不限",
}

_EDU_FALLBACK = {"学历不限", "大专", "本科", "硕士"}

_BOSS_FILES = ["boss_nanjing.csv", "boss_hangzhou.csv"]
_51JOB_FILES = ["51job_shujufenxi.csv", "51job_caiwu.csv", "51job_yinhang.csv"]

_BOSS_SOURCE = "boss_zhipin_202508"
_51JOB_SOURCE = "51job_2025"


# -----------------------------------------------------------------------
# 薪资解析
# -----------------------------------------------------------------------

def parse_salary(raw: str) -> tuple[float | None, float | None, str, int | None]:
    """解析薪资字符串，返回 (min, max, unit, months)。

    支持：10-15K, 20-30K·13薪, 6-8.5千, 1-1.6万, 120-150元/天,
         7-12万/年, 30-50万/年
    """
    if not raw or not isinstance(raw, str):
        return None, None, "month", None

    s = raw.strip()
    months: int | None = None

    # 提取薪月数
    m = re.search(r"(\d+)薪", s)
    if m:
        months = int(m.group(1))

    # 日薪：120-150元/天
    m = re.match(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*元/天", s)
    if m:
        return float(m.group(1)), float(m.group(2)), "day", months

    # 万/年：7-12万/年, 30-50万/年 → 按年折算月薪（/12）
    m = re.match(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*万/年", s)
    if m:
        lo = float(m.group(1)) * 10000 / 12
        hi = float(m.group(2)) * 10000 / 12
        return round(lo, 2), round(hi, 2), "month", months

    # 万：1-1.6万, 1.5-2万
    m = re.match(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*万", s)
    if m:
        lo = float(m.group(1)) * 10000
        hi = float(m.group(2)) * 10000
        return lo, hi, "month", months

    # 千：6-8.5千, 8千-1万
    m = re.match(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*千", s)
    if m:
        lo = float(m.group(1)) * 1000
        hi = float(m.group(2)) * 1000
        return lo, hi, "month", months

    # K：10-15K, 20-30K
    m = re.match(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*[Kk]", s)
    if m:
        lo = float(m.group(1)) * 1000
        hi = float(m.group(2)) * 1000
        return lo, hi, "month", months

    # 混合格式：8千-1万, 7.8千-1.4万, 8千-1.5万·13薪 → 千和万混合
    m = re.match(r"(\d+(?:\.\d+)?)\s*千\s*[-~]\s*(\d+(?:\.\d+)?)\s*万", s)
    if m:
        lo = float(m.group(1)) * 1000
        hi = float(m.group(2)) * 10000
        return lo, hi, "month", months

    # 单值日薪：180元/天, 4千/天
    m = re.match(r"(\d+(?:\.\d+)?)\s*(千元?|万)*/天", s)
    if m:
        base = float(m.group(1))
        unit_str = m.group(2) or ""
        if "万" in unit_str:
            base *= 10000
        elif "千" in unit_str:
            base *= 1000
        return base, base, "day", months

    # 日薪范围乱码编码（Boss 薪资列编码异常）：15000-25000?/?  → 按数值范围处理
    m = re.match(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)", s)
    if m and ("/" in s or "元" in s or "天" in s or "时" in s):
        return float(m.group(1)), float(m.group(2)), "day", months

    # 单值日薪乱码：60-100?/?  (时薪范围 → 日薪)
    # 已被上面捕获

    # "3千及以下" → (3000, 3000)
    m = re.match(r"(\d+(?:\.\d+)?)\s*千及以下", s)
    if m:
        v = float(m.group(1)) * 1000
        return v, v, "month", months

    # "X万以上" → (X万, X万)
    m = re.match(r"(\d+(?:\.\d+)?)\s*万以上", s)
    if m:
        v = float(m.group(1)) * 10000
        return v, v, "month", months

    # "X千以上" → (X千, X千)
    m = re.match(r"(\d+(?:\.\d+)?)\s*千以上", s)
    if m:
        v = float(m.group(1)) * 1000
        return v, v, "month", months

    return None, None, "month", None


# -----------------------------------------------------------------------
# 经验解析
# -----------------------------------------------------------------------

def parse_exp(raw: str) -> tuple[int, int]:
    """解析经验字符串，返回 (exp_min, exp_max)。"""
    if not raw or not isinstance(raw, str):
        return 0, 0
    s = raw.strip()

    # 无需经验/经验不限/在校应届/应届
    if any(k in s for k in ("无需", "不限", "在校", "应届", "无经验")):
        return 0, 0

    # X年及以上
    m = re.match(r"(\d+)\s*年及以上", s)
    if m:
        return int(m.group(1)), 99

    # X-Y年
    m = re.match(r"(\d+)\s*[-~]\s*(\d+)\s*年", s)
    if m:
        return int(m.group(1)), int(m.group(2))

    # X年
    m = re.match(r"(\d+)\s*年", s)
    if m:
        n = int(m.group(1))
        return n, 99

    # Boss 实习：5天/周 5个月
    if "天/周" in s or "个月" in s:
        return 0, 0

    return 0, 0


def is_internship(exp_str: str) -> bool:
    """判断是否为实习岗（Boss 的 5天/周 5个月 格式）。"""
    if not exp_str:
        return False
    return "天/周" in exp_str or "个月" in exp_str


# -----------------------------------------------------------------------
# 学历解析
# -----------------------------------------------------------------------

def parse_edu(raw: str) -> str:
    """解析学历字符串，返回枚举值。"""
    if not raw or not isinstance(raw, str):
        return "学历不限"
    s = raw.strip()
    for key, val in _EDU_MAP.items():
        if key in s:
            return val
    # 如果本身就是枚举值
    if s in _EDU_FALLBACK:
        return s
    return "学历不限"


# -----------------------------------------------------------------------
# 城市拆分
# -----------------------------------------------------------------------

def split_city_district(raw: str) -> tuple[str, str]:
    """拆分城市与区，如 '南京·浦口区' → ('南京', '浦口区')。"""
    if not raw or not isinstance(raw, str):
        return "", ""
    s = raw.strip()
    if "·" in s:
        parts = s.split("·", 1)
        city = parts[0].strip()
        district = parts[1].strip() if len(parts) > 1 else ""
        return city, district
    return s, ""


# -----------------------------------------------------------------------
# Boss 数据清洗
# -----------------------------------------------------------------------

def clean_boss(file_path: Path) -> pd.DataFrame:
    """清洗单个 Boss 直聘 CSV 文件。"""
    source = _BOSS_SOURCE
    df = pd.read_csv(file_path, encoding="utf-8-sig", dtype=str).fillna("")

    rows: list[dict[str, Any]] = []
    n_drop = 0

    for _, r in df.iterrows():
        title = str(r.get("name", "")).strip()
        company = str(r.get("company_name.1", "")).strip() or str(r.get("company_name", "")).strip()
        if not title or not company:
            n_drop += 1
            continue

        # job_tags: 城市\n经验\n学历
        tags_raw = str(r.get("job_tags", "")).strip()
        tag_lines = [t.strip() for t in tags_raw.split("\n") if t.strip()]
        city_raw = tag_lines[0] if len(tag_lines) >= 1 else ""
        exp_raw = tag_lines[1] if len(tag_lines) >= 2 else ""
        edu_raw = tag_lines[2] if len(tag_lines) >= 3 else ""

        city, district = split_city_district(city_raw)

        # 实习检测
        is_intern = is_internship(exp_raw)
        if is_intern:
            title = f"[实习]{title}"

        exp_min, exp_max = parse_exp(exp_raw)
        education = parse_edu(edu_raw)

        # 薪资
        sal_raw = str(r.get("salary", "")).strip()
        sal_min, sal_max, sal_unit, sal_months = parse_salary(sal_raw)
        if sal_min is None:
            n_drop += 1
            continue

        # company_tag: ['融资阶段','规模','行业']
        ctag_raw = str(r.get("company_tag", "")).strip()
        industry = ""
        company_size = ""
        if ctag_raw and ctag_raw.startswith("["):
            try:
                tags = ast.literal_eval(ctag_raw)
                if isinstance(tags, list):
                    # 通常是 [融资阶段, 规模, 行业]
                    if len(tags) >= 3:
                        company_size = tags[1]
                        industry = tags[2]
                    elif len(tags) == 2:
                        company_size = tags[0]
                        industry = tags[1]
            except (ValueError, SyntaxError):
                pass

        # job_label → skill_tags
        skill_tags_raw = str(r.get("job_label", "")).strip()
        skill_tags = [t for t in re.split(r"[,，;；\n]", skill_tags_raw) if t.strip()] if skill_tags_raw else []

        # job_desc → description（脱敏）
        desc = mask_text(str(r.get("job_desc", "")).strip())

        # raw_key
        raw_key = hashlib.md5(f"{company}|{title}|{city}".encode()).hexdigest()

        rows.append({
            "title": title,
            "company": company,
            "industry": industry,
            "company_size": company_size,
            "city": city,
            "district": district,
            "salary_min": sal_min,
            "salary_max": sal_max,
            "salary_unit": sal_unit,
            "salary_months": sal_months,
            "exp_min": exp_min,
            "exp_max": exp_max,
            "education": education,
            "skill_tags": skill_tags,
            "benefits": "",
            "description": desc,
            "source": source,
            "raw_key": raw_key,
        })

    result = pd.DataFrame(rows, columns=OUTPUT_COLS)
    return result, len(df), len(result), n_drop


# -----------------------------------------------------------------------
# 51job 数据清洗
# -----------------------------------------------------------------------

def clean_51job(file_path: Path) -> tuple[pd.DataFrame, int, int, int]:
    """清洗单个前程无忧 CSV 文件。"""
    source = _51JOB_SOURCE
    df = pd.read_csv(file_path, encoding="utf-8-sig", dtype=str).fillna("")

    rows: list[dict[str, Any]] = []
    n_drop = 0

    for _, r in df.iterrows():
        title = str(r.get("职位", "")).strip()
        company = str(r.get("公司", "")).strip()
        if not title or not company:
            n_drop += 1
            continue

        city_raw = str(r.get("城市", "")).strip()
        city, district = split_city_district(city_raw)

        exp_raw = str(r.get("经验", "")).strip()
        exp_min, exp_max = parse_exp(exp_raw)
        education = parse_edu(str(r.get("学历", "")).strip())

        sal_raw = str(r.get("薪资", "")).strip()
        sal_min, sal_max, sal_unit, sal_months = parse_salary(sal_raw)
        if sal_min is None:
            n_drop += 1
            continue

        industry = str(r.get("公司领域", "")).strip()
        company_size = str(r.get("公司规模", "")).strip()

        # 福利标签 ; 分隔
        benefits_raw = str(r.get("福利标签", "")).strip()
        benefits = [t for t in benefits_raw.split(";") if t.strip()] if benefits_raw else []

        # 技能标签 ; 分隔
        skills_raw = str(r.get("技能标签", "")).strip()
        skill_tags = [t for t in skills_raw.split(";") if t.strip()] if skills_raw else []

        desc = mask_text(str(r.get("岗位描述", "")).strip())

        raw_key = hashlib.md5(f"{company}|{title}|{city}".encode()).hexdigest()

        rows.append({
            "title": title,
            "company": company,
            "industry": industry,
            "company_size": company_size,
            "city": city,
            "district": district,
            "salary_min": sal_min,
            "salary_max": sal_max,
            "salary_unit": sal_unit,
            "salary_months": sal_months,
            "exp_min": exp_min,
            "exp_max": exp_max,
            "education": education,
            "skill_tags": skill_tags,
            "benefits": benefits,
            "description": desc,
            "source": source,
            "raw_key": raw_key,
        })

    result = pd.DataFrame(rows, columns=OUTPUT_COLS)
    return result, len(df), len(result), n_drop


# -----------------------------------------------------------------------
# 主清洗函数
# -----------------------------------------------------------------------

def clean_all() -> tuple[pd.DataFrame, list[dict]]:
    """清洗全部 5 个文件，返回 (合并 DataFrame, 各文件统计)。"""
    stats: list[dict] = []
    all_dfs: list[pd.DataFrame] = []

    for fname in _BOSS_FILES:
        fp = _RAW_DIR / fname
        if not fp.exists():
            print(f"  [SKIP] {fname} 不存在")
            continue
        df, n_in, n_out, n_drop = clean_boss(fp)
        all_dfs.append(df)
        stats.append({
            "file": fname, "source": _BOSS_SOURCE,
            "input": n_in, "output": n_out, "dropped": n_drop,
        })
        print(f"  {fname}: {n_in} -> {n_out} (drop {n_drop})")

    for fname in _51JOB_FILES:
        fp = _RAW_DIR / fname
        if not fp.exists():
            print(f"  [SKIP] {fname} 不存在")
            continue
        df, n_in, n_out, n_drop = clean_51job(fp)
        all_dfs.append(df)
        stats.append({
            "file": fname, "source": _51JOB_SOURCE,
            "input": n_in, "output": n_out, "dropped": n_drop,
        })
        print(f"  {fname}: {n_in} -> {n_out} (drop {n_drop})")

    if not all_dfs:
        return pd.DataFrame(columns=OUTPUT_COLS), stats

    combined = pd.concat(all_dfs, ignore_index=True)

    # 去重（raw_key 重复保留第一条）
    before = len(combined)
    combined = combined.drop_duplicates(subset=["raw_key"], keep="first")
    after = len(combined)
    print(f"  去重: {before} -> {after} (removed {before - after})")

    return combined, stats


def save_cleaned(df: pd.DataFrame) -> Path:
    """保存清洗结果到 data/cleaned/jobs_cleaned.csv。"""
    _CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _CLEAN_DIR / "jobs_cleaned.csv"
    # JSON 列序列化
    df_out = df.copy()
    for col in ("skill_tags", "benefits"):
        df_out[col] = df_out[col].apply(lambda v: ";".join(v) if isinstance(v, list) else "")
    df_out.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out_path


if __name__ == "__main__":
    print("清洗 data/raw/ 下 5 个招聘 CSV...")
    df, stats = clean_all()
    out = save_cleaned(df)
    total_in = sum(s["input"] for s in stats)
    total_out = sum(s["output"] for s in stats)
    total_drop = sum(s["dropped"] for s in stats)
    print(f"\n汇总: {total_in} -> {len(df)} (drop {total_drop})")
    if total_in > 0:
        rate = (total_in - total_drop) / total_in * 100
        print(f"薪资解析成功率: {rate:.1f}%")
    print(f"输出: {out}")
