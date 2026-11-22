# app/exporters.py
# 职责：把二维数据渲染成 xlsx / csv / json 三种下载格式
# 依赖：标准库 + openpyxl（仅 xlsx 分支按需导入）
# 说明：三种格式共用同一份 (headers, rows)，保证「导出的数字永远一致」，
#       区别只在容器，不在口径——避免 CSV 和 Excel 两套取数逻辑漂移。

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Iterable, Sequence
from urllib.parse import quote

from fastapi import Response

FORMATS: tuple[str, ...] = ("xlsx", "csv", "json")

XLSX_MIME = ("application/vnd.openxmlformats-officedocument"
             ".spreadsheetml.sheet")
MIME = {
    "xlsx": XLSX_MIME,
    "csv": "text/csv; charset=utf-8",
    "json": "application/json; charset=utf-8",
}


def stamp() -> str:
    """文件名时间戳：同一分钟内多次导出也不会互相覆盖。"""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def content_disposition(filename: str, ascii_stem: str = "") -> str:
    """中文文件名按 RFC 5987 双写：ASCII 兜底名 + UTF-8 实名。

    只给 filename= 的话，浏览器遇到中文会存成 `%E5%AD%A6...` 或直接丢扩展名；
    而把中文整段删掉又会留下 `--AI2301.xlsx` 这种脏名字，所以单独给一个英文 stem。
    """
    ext = filename[filename.rfind("."):] if "." in filename else ""
    # 兜底名必须是纯 ASCII（中文班级名会再次落空），过滤后为空就用 export
    fallback = ((ascii_stem or "").encode("ascii", "ignore").decode()
                .strip("-_ ") or "export") + ext
    return (f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(filename)}")


def _cell(value: Any) -> Any:
    """统一空值：None 落成空字符串，避免表格里出现字面量 'None'。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    return value


def to_csv(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> bytes:
    """CSV 带 UTF-8 BOM：不加的话 Excel 双击打开中文全是乱码。"""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(list(headers))
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def to_json(payload: Any) -> bytes:
    """JSON 保留中文原样（ensure_ascii=False），Decimal/日期用 str 兜底。"""
    return json.dumps(payload, ensure_ascii=False, indent=2,
                      default=str).encode("utf-8")


def to_xlsx(sheets: Sequence[tuple[str, Sequence[str], Iterable[Sequence[Any]]]]) -> bytes:
    """多 sheet 工作簿；表头深蓝底白字、冻结首行、自动筛选、列宽按内容自适应。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    head_fill = PatternFill("solid", fgColor="1F4E79")
    head_font = Font(color="FFFFFF", bold=True, size=11)
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for name, headers, rows in sheets:
        ws = wb.create_sheet(title=str(name)[:31] or "Sheet1")
        ws.append([str(h) for h in headers])
        for cell in ws[1]:
            cell.fill = head_fill
            cell.font = head_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for row in rows:
            ws.append([_cell(v) for v in row])

        # 列宽：中文按 1.9 倍字宽估算，夹在 8~42 之间，避免一列撑满整屏
        for idx in range(1, len(headers) + 1):
            width = 0
            for cell in ws[get_column_letter(idx)]:
                if cell.value not in (None, ""):
                    text = str(cell.value)
                    # 中文占两个字符宽
                    width = max(width, sum(2 if ord(ch) > 127 else 1 for ch in text))
            ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 4, 8), 42)

        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row,
                                max_col=len(headers)):
            for cell in row:
                cell.border = border

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_response(fmt: str, filename_stem: str,
                   headers: Sequence[str] | None = None,
                   rows: Iterable[Sequence[Any]] | None = None,
                   sheets: Sequence[tuple[str, Sequence[str], Iterable[Sequence[Any]]]] | None = None,
                   payload: Any = None,
                   ascii_stem: str = "") -> Response:
    """按格式产出下载响应。

    - xlsx：优先用 sheets（多表），退化为单表 headers/rows
    - csv ：只能用单表 headers/rows
    - json：用 payload（完整结构化数据，便于二次处理）
    """
    fmt = str(fmt or "xlsx").lower()
    if fmt not in FORMATS:
        fmt = "xlsx"

    filename = f"{filename_stem}-{stamp()}.{fmt}"
    if fmt == "json":
        body = to_json(payload if payload is not None else {
            "headers": list(headers or []),
            "rows": [list(map(_cell, r)) for r in (rows or [])],
        })
    elif fmt == "csv":
        body = to_csv(headers or [], rows or [])
    else:
        if sheets:
            body = to_xlsx(sheets)
        else:
            body = to_xlsx([(filename_stem[:31], headers or [], rows or [])])

    return Response(
        content=body,
        media_type=MIME[fmt],
        headers={
            "Content-Disposition": content_disposition(filename, ascii_stem),
            # 让前端能读到文件名（同源下也安全）
            "Access-Control-Expose-Headers": "Content-Disposition",
            "Cache-Control": "no-store",
        },
    )
