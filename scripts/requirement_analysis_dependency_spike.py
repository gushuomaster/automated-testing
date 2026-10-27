"""依赖实测；仅生成开发小样，不产生语义能力验收成绩。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import platform
import subprocess
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from docx import Document
from markdown_it import MarkdownIt
from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas


def _write_deterministic_docx(document: Document, path: Path) -> None:
    fixed = datetime(2020, 1, 1, tzinfo=timezone.utc)
    document.core_properties.created = fixed
    document.core_properties.modified = fixed
    buffer = BytesIO(); document.save(buffer)
    output = BytesIO()
    with ZipFile(BytesIO(buffer.getvalue()), "r") as source, ZipFile(output, "w") as target:
        for name in sorted(source.namelist()):
            info = ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            target.writestr(info, source.read(name))
    path.write_bytes(output.getvalue())


def create_samples(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    paths = {ext: root / f"中文需求小样.{ext}" for ext in ("md", "docx", "pdf")}
    paths["md"].write_text(
        "# 订单\n\n数量范围为 1 至 999，包含边界。\n\n"
        "| 字段 | 规则 |\n| --- | --- |\n| 单价 | 最多两位小数 |\n\n"
        "## 查询\n\n订单编号精确查询。\n", encoding="utf-8"
    )
    doc = Document()
    doc.add_heading("订单", 1)
    doc.add_paragraph("数量范围为 1 至 999，包含边界。")
    table = doc.add_table(rows=2, cols=2)
    for row, values in zip(table.rows, (("字段", "规则"), ("单价", "最多两位小数"))):
        for cell, value in zip(row.cells, values):
            cell.text = value
    doc.add_page_break()
    doc.add_heading("查询", 2)
    doc.add_paragraph("订单编号精确查询。")
    _write_deterministic_docx(doc, paths["docx"])
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    canvas = Canvas(str(paths["pdf"]), invariant=1)
    canvas.setFont("STSong-Light", 12)
    for y, text in ((800, "订单"), (776, "数量范围为 1 至 999，包含边界。"),
                    (748, "字段          规则"), (724, "单价          最多两位小数")):
        canvas.drawString(72, y, text)
    canvas.showPage()
    canvas.setFont("STSong-Light", 12)
    canvas.drawString(72, 800, "查询")
    canvas.drawString(72, 776, "订单编号精确查询。")
    canvas.save()
    return paths


def run(root: Path) -> dict:
    paths = create_samples(root / "samples")
    document = Document(paths["docx"])
    docx_text = "\n".join(p.text for p in document.paragraphs)
    cell_text = document.tables[0].cell(1, 1).text
    tokens = MarkdownIt("commonmark").enable("table").parse(paths["md"].read_text(encoding="utf-8"))
    reader = PdfReader(paths["pdf"])
    visits: list[dict] = []
    for page_number, page in enumerate(reader.pages, 1):
        def visitor(text, cm, tm, font, size):
            if text.strip():
                visits.append({"page": page_number, "text": text, "cm": cm, "tm": tm})
        page.extract_text(visitor_text=visitor)
    assert "数量范围为 1 至 999，包含边界。" in docx_text
    assert cell_text == "最多两位小数"
    assert 'w:type="page"' in document.element.xml
    assert any(t.type == "table_open" and t.map for t in tokens)
    assert "订单编号精确查询。" in "".join(v["text"] for v in visits)
    assert "数量范围为 1 至 999，包含边界。" in "".join(v["text"] for v in visits)
    assert {v["page"] for v in visits} == {1, 2}
    packages = []
    for name in ("python-docx", "lxml", "pypdf", "markdown-it-py", "jsonschema", "reportlab"):
        dist = metadata.distribution(name)
        packages.append({"name": name, "version": dist.version,
                         "license": dist.metadata.get("License-Expression") or dist.metadata.get("License"),
                         "python": dist.metadata.get("Requires-Python"),
                         "wheel": dist.read_text("WHEEL")})
    result = {"python": platform.python_version(), "platform": platform.platform(),
              "packages": packages, "assertions": "passed", "pdf_visits": visits,
              "samples": {ext: {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                          for ext, p in paths.items()},
              "limits": ["PDF 表格只保留文本与位置，不能据此声称表格语义恢复。",
                         "DOCX 页码为显式分页标记，不是 Word 渲染页码。",
                         "Linux/Kylin 需单独实测，Windows wheel 成功不是跨平台运行证据。"]}
    (root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/requirement-analysis/dependency-spike"))
    result = run(parser.parse_args().output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
