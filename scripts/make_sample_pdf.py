# scripts/make_sample_pdf.py
# 职责：生成一个最小的、可被 pypdf 解析的多页 PDF，用于验证「PDF 按页抽取 + 页码引用」。
# 说明：只用 Helvetica 内置字体，因此正文是 ASCII；中文 PDF（带嵌入字体）走同一条抽取通道。
#       这不是演示用的假数据，而是测试夹具：它验证的是解析与页码归属，不是语义效果。

from __future__ import annotations

from pathlib import Path


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_pdf(pages: list[list[str]]) -> bytes:
    """pages = [[第1页每行文本], [第2页...]]，返回 PDF 字节。"""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)          # 对象号从 1 开始

    catalog = add(b"")            # 占位，最后回填
    pages_id = add(b"")
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids: list[int] = []
    for lines in pages:
        content = ["BT", "/F1 12 Tf", "72 760 Td", "14 TL"]
        for i, line in enumerate(lines):
            if i:
                content.append("T*")
            content.append(f"({_escape(line)}) Tj")
        content.append("ET")
        stream = "\n".join(content).encode("latin-1", errors="replace")
        content_id = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
                         + stream + b"\nendstream")
        page_ids.append(add(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode()))

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objs[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    objs[catalog - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    return bytes(out)


def write_sample(path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_pdf([
        ["Employee Reimbursement Policy", "Section 1 Travel",
         "Submit a travel request before departure; manager approval required.",
         "Hotel cap: 500 CNY per night in tier-1 cities, 350 CNY elsewhere."],
        ["Section 2 Deadline",
         "Submit receipts within 30 days after the expense occurs.",
         "Late claims need a director signature explaining the delay."],
    ]))
    return path


if __name__ == "__main__":
    p = write_sample(Path(__file__).resolve().parent.parent / "data" / "samples" / "reimbursement_policy.pdf")
    print(f"written: {p} ({p.stat().st_size} bytes)")
