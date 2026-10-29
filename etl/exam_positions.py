# etl/exam_positions.py
# 职责：抓取并解析国家公务员局《招考简章》职位表（.xls），转成结构化职位记录。
# 依赖：xlrd（旧版 .xls 只读）、标准库 urllib / zipfile / hashlib / pathlib。
# 原则：只解析、只归一字段，不推断不补全；空值留 None，解析失败抛异常交给调用方记录。

from __future__ import annotations

import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Iterable, Sequence

POSITION_SOURCE = "scs-gk"
POSITION_SOURCE_NAME = "国家公务员局·中央机关及其直属机构考试录用公务员专题"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
_TIMEOUT = 120

# 官方专题与《招考简章》下载地址按年度登记；未知年度必须显式传 url，不猜。
OFFICIAL_TOPIC: dict[int, str] = {
    2027: "http://bm.scs.gov.cn/kl2027/",
}
DOWNLOAD_URLS: dict[int, str] = {
    2027: "http://dl.scs.gov.cn/download/8a81f6d1a129c3d401a133dca26b00d2",
}

# 源表列名 → 记录键（与 db/guokao_positions.sql 的中文列一一对应）
COLUMN_MAP: dict[str, str] = {
    "部门代码": "dept_code",
    "部门名称": "dept_name",
    "用人司局": "bureau",
    "机构性质": "org_nature",
    "招考职位": "position_name",
    "职位属性": "position_attr",
    "职位分布": "position_dist",
    "职位简介": "intro",
    "职位代码": "position_code",
    "机构层级": "org_level",
    "考试类别": "exam_category",
    "招考人数": "headcount",
    "专业": "major",
    "学历": "education",
    "学位": "degree",
    "政治面貌": "political",
    "基层工作最低年限": "work_years",
    "服务基层项目工作经历": "grassroots_project",
    "是否在面试阶段组织专业能力测试": "pro_test",
    "面试人员比例": "interview_ratio",
    "工作地点": "work_place",
    "落户地点": "settle_place",
    "备注": "remark",
    "部门网站": "dept_site",
    "咨询电话1": "phone1",
    "咨询电话2": "phone2",
    "咨询电话3": "phone3",
}
_REQUIRED_HEADERS = ("部门代码", "部门名称", "招考职位", "职位代码")


def official_topic_url(year: int) -> str:
    """返回该年度官方专题地址；未登记年度返回空串（不编 URL）。"""
    return OFFICIAL_TOPIC.get(int(year), "")


def source_key(year: int, dept_code: str, position_code: str) -> str:
    """幂等键：年度 + 部门代码 + 职位代码（源表里这组值唯一）。"""
    raw = f"{int(year)}|{dept_code.strip()}|{position_code.strip()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    """单元格转字符串并去首尾空白；整数值的 float 不带 .0。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace("\r\n", "\n").strip()


def _to_int(value: Any) -> int | None:
    """招考人数转整数；空值或非数字返回 None（不猜）。"""
    text = _text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _find_header(rows: Sequence[Sequence[Any]]) -> tuple[int, list[str]]:
    """在前 8 行里找表头行（同时包含部门代码/部门名称/招考职位/职位代码）。"""
    for idx, row in enumerate(rows[:8]):
        headers = [_text(c) for c in row]
        if all(h in headers for h in _REQUIRED_HEADERS):
            return idx, headers
    raise ValueError("没有找到职位表表头（需要 部门代码/部门名称/招考职位/职位代码）")


def parse_rows(rows: Iterable[Sequence[Any]], year: int, category: str = "",
               data_file: str = "") -> list[dict[str, Any]]:
    """把一张 sheet 的二维单元格解析成职位记录列表（纯函数，便于单测）。"""
    matrix = [list(row) for row in rows]
    if not matrix:
        return []
    header_idx, headers = _find_header(matrix)
    index_by_key = {COLUMN_MAP[h]: i for i, h in enumerate(headers) if h in COLUMN_MAP}
    if "dept_code" not in index_by_key or "position_code" not in index_by_key:
        raise ValueError("表头缺少 部门代码 / 职位代码")

    records: list[dict[str, Any]] = []
    for row in matrix[header_idx + 1:]:
        def cell(key: str) -> Any:
            idx = index_by_key.get(key)
            return row[idx] if idx is not None and idx < len(row) else None

        dept_code = _text(cell("dept_code"))
        position_code = _text(cell("position_code"))
        if not dept_code or not position_code:
            continue                       # 空行/合计行：直接跳过，不编记录
        record: dict[str, Any] = {
            "year": int(year),
            "source": POSITION_SOURCE,
            "source_key": source_key(year, dept_code, position_code),
            "category": category,
            "dept_code": dept_code,
            "dept_name": _text(cell("dept_name")),
            "bureau": _text(cell("bureau")),
            "org_nature": _text(cell("org_nature")),
            "position_name": _text(cell("position_name")),
            "position_attr": _text(cell("position_attr")),
            "position_dist": _text(cell("position_dist")),
            "intro": _text(cell("intro")),
            "position_code": position_code,
            "org_level": _text(cell("org_level")),
            "exam_category": _text(cell("exam_category")),
            "headcount": _to_int(cell("headcount")),
            "major": _text(cell("major")),
            "education": _text(cell("education")),
            "degree": _text(cell("degree")),
            "political": _text(cell("political")),
            "work_years": _text(cell("work_years")),
            "grassroots_project": _text(cell("grassroots_project")),
            "pro_test": _text(cell("pro_test")),
            "interview_ratio": _text(cell("interview_ratio")),
            "work_place": _text(cell("work_place")),
            "settle_place": _text(cell("settle_place")),
            "remark": _text(cell("remark")),
            "dept_site": _text(cell("dept_site")),
            "phone1": _text(cell("phone1")),
            "phone2": _text(cell("phone2")),
            "phone3": _text(cell("phone3")),
            "notice_url": official_topic_url(year),
            "data_file": data_file,
        }
        records.append(record)
    return records


def parse_position_xls(xls_path: Path, year: int) -> list[dict[str, Any]]:
    """解析官方 .xls：逐个有效 sheet 调 parse_rows，返回全部职位记录。"""
    import xlrd

    book = xlrd.open_workbook(str(xls_path), on_demand=True)
    out: list[dict[str, Any]] = []
    try:
        for sheet in book.sheets():
            if sheet.nrows < 3 or sheet.ncols < len(_REQUIRED_HEADERS):
                continue
            rows = [[sheet.cell_value(r, c) for c in range(sheet.ncols)]
                    for r in range(sheet.nrows)]
            out.extend(parse_rows(rows, year=year, category=sheet.name,
                                  data_file=xls_path.name))
    finally:
        book.release_resources()
    if not out:
        raise ValueError(f"{xls_path.name} 里没有解析到任何职位")
    return out


def download_positions(year: int, dest_dir: Path, url: str | None = None) -> Path:
    """下载官方《招考简章》zip 到 dest_dir；返回 zip 路径。"""
    target_url = url or DOWNLOAD_URLS.get(int(year))
    if not target_url:
        raise ValueError(f"{year} 年度没有登记官方下载地址，请用 url 参数显式指定")
    dest_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(target_url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = resp.read()
    if not data.startswith(b"PK"):
        raise ValueError(f"下载内容不是 zip（前 4 字节 {data[:4]!r}），地址可能已失效")
    target = dest_dir / f"招考简章_{int(year)}.zip"
    target.write_bytes(data)
    return target


def extract_xls(zip_path: Path, dest_dir: Path) -> Path:
    """从 zip 中取出第一个 Excel 文件；只写目标目录下的文件名，防目录穿越。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        members = [name for name in archive.namelist()
                   if name.lower().endswith((".xls", ".xlsx"))
                   and not name.startswith("__MACOSX/")]
        if not members:
            raise ValueError(f"{zip_path.name} 里没有 Excel 文件")
        member = members[0]
        target = dest_dir / Path(member).name
        with archive.open(member) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return target


def load_from_path(path: Path, year: int) -> list[dict[str, Any]]:
    """从 zip 或 .xls 读取职位记录（zip 会先解压到同目录）。"""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        xls_path = extract_xls(path, path.parent)
    elif path.suffix.lower() == ".xls":
        xls_path = path
    elif path.suffix.lower() == ".xlsx":
        raise ValueError("官方招考简章是 .xls；.xlsx 需要 openpyxl，未纳入依赖")
    else:
        raise ValueError(f"不支持的文件类型：{path.suffix}")
    return parse_position_xls(xls_path, year)
