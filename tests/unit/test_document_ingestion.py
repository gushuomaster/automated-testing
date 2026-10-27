from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys

import pytest
from docx import Document
from docx.oxml import OxmlElement
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader

from testing_platform.domain.documents import digest
from testing_platform.infrastructure.documents.ingestion import create_manifest, ingest, ingest_manifest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from requirement_analysis_dependency_spike import create_samples


def parse(path):
    return ingest(create_manifest([path], role="development").files[0])


def test_manifest_versions_duplicates_readonly_and_snapshot(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    first, second = a / "同名.md", b / "同名.md"
    first.write_text("甲", encoding="utf-8"); second.write_text("乙", encoding="utf-8")
    config = {"nested": {"value": 1}}
    first.chmod(0o444)
    try:
        manifest = create_manifest([first, first, second], role="development", config=config)
        config["nested"]["value"] = 2
        assert len(manifest.files) == 2 and len(manifest.duplicate_paths) == 1
        assert manifest.files[0].document_id != manifest.files[1].document_id
        assert manifest.config["nested"]["value"] == 1
        assert first.read_text(encoding="utf-8") == "甲"
        aggregate = ingest_manifest(manifest)
        assert len(aggregate.documents) == 2 and aggregate.summary.total == 2
        assert aggregate == ingest_manifest(manifest)
    finally:
        first.chmod(0o666)
    first.write_text("冻结后变更", encoding="utf-8")
    result = ingest(manifest.files[0])
    assert result.status == "failed" and "冻结后" in result.issues[0].message


def test_markdown_structure_source_order_and_stability(tmp_path):
    path = tmp_path / "需求.md"
    text = "# 一级\n\n## 二级\n\n- 中文一\n- 中文二\n\n| 列 | 值 |\n|---|---|\n| 甲 | 1 |\n\n```python\nx=1\n```\n\n![图](x.png)\n\n最后。\n"
    path.write_text(text, encoding="utf-8")
    first, second = parse(path), parse(path)
    assert first == second
    assert {s.kind for s in first.segments} >= {"heading", "list_item", "table", "fence", "inline_object"}
    assert "bullet_list" not in {s.kind for s in first.segments}
    assert len([s for s in first.segments if "中文一" in s.text]) == 1
    assert [s.heading_level for s in first.segments if s.kind == "heading"] == [1, 2]
    for segment in first.segments:
        locator = segment.locator
        assert 1 <= locator.line_start <= locator.line_end <= len(text.splitlines())
        assert segment.content_sha256 == digest(segment.text.encode("utf-8"))
    image = next(s for s in first.segments if s.kind == "inline_object")
    last = next(s for s in first.segments if s.text == "最后。")
    assert image.order < last.order


def test_docx_interleaves_tables_objects_and_breaks(tmp_path):
    path = tmp_path / "需求.docx"
    doc = Document()
    doc.add_heading("中文标题", 1)
    doc.add_paragraph("前文")
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "单元格需求"
    doc.add_page_break()
    paragraph = doc.add_paragraph("后文")
    paragraph._p.append(OxmlElement("m:oMath"))
    image = BytesIO(); Image.new("RGB", (5, 5), "white").save(image, format="PNG"); image.seek(0)
    doc.add_picture(image)
    paragraph._p.append(OxmlElement("w:object"))
    doc.save(path)
    result = parse(path)
    assert result == parse(path)
    texts = [s.text for s in result.segments if s.text]
    assert texts.index("前文") < texts.index("单元格需求") < texts.index("后文")
    assert {s.kind for s in result.segments} >= {"heading", "table_cell", "explicit_page_break", "drawing", "oMath", "object"}
    for segment in result.segments:
        assert segment.locator.part and segment.locator.xpath
    unknown = [s for s in result.segments if s.status == "unknown"]
    assert len(unknown) == 3
    assert all(any(i.segment_id == s.id for i in result.issues) for s in unknown)


def test_pdf_chinese_coordinates_blank_and_no_text(tmp_path):
    samples = create_samples(tmp_path / "samples")
    writer = PdfWriter()
    for page in PdfReader(samples["pdf"]).pages:
        writer.add_page(page)
    writer.add_blank_page(600, 800)
    image_pdf = BytesIO()
    canvas = Canvas(image_pdf)
    canvas.drawImage(ImageReader(Image.new("RGB", (5, 5), "black")), 10, 10, 50, 50)
    canvas.save()
    writer.add_page(PdfReader(image_pdf).pages[0])
    path = tmp_path / "混合.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    result = parse(path)
    assert result == parse(path)
    assert "数量范围为 1 至 999，包含边界。" in "".join(s.text for s in result.segments)
    text = next(s for s in result.segments if s.text.startswith("数量"))
    assert text.locator.page == 1 and text.locator.x == 72 and text.locator.y == 776
    assert any(i.code == "PDF_EMPTY_PAGE" and i.locator.page == 3 for i in result.issues)
    assert any(i.code == "PDF_NO_TEXT_LAYER" and i.locator.page == 4 for i in result.issues)


def test_three_formats_equivalent_rules_and_explicit_failure(tmp_path):
    samples = create_samples(tmp_path)
    for path in samples.values():
        result = parse(path)
        text = "\n".join(s.text for s in result.segments)
        assert "数量范围为 1 至 999，包含边界。" in text
        assert "最多两位小数" in text
        assert "订单编号精确查询。" in text
        assert path.read_bytes() and result.source.sha256 == digest(path.read_bytes())
    corrupt = tmp_path / "broken.docx"; corrupt.write_bytes(b"bad zip")
    assert parse(corrupt).status == "failed"
    unsupported = tmp_path / "image.png"; unsupported.write_bytes(b"not parsed")
    assert parse(unsupported).status == "unsupported"
    empty = tmp_path / "empty.md"; empty.write_bytes(b"")
    assert parse(empty).issues[0].code == "EMPTY_DOCUMENT"
    manifest = create_manifest([*samples.values(), corrupt, unsupported, empty], role="development")
    report = ingest_manifest(manifest)
    assert report.summary.model_dump() == {"total": 6, "parsed": 1, "partial": 2, "failed": 2,
                                           "unsupported": 1, "issue_count": sum(len(d.issues) for d in report.documents)}


def test_equivalence_set_reinitializes_to_identical_bytes(tmp_path):
    first = create_samples(tmp_path / "first")
    second = create_samples(tmp_path / "second")
    assert {suffix: digest(path.read_bytes()) for suffix, path in first.items()} == {
        suffix: digest(path.read_bytes()) for suffix, path in second.items()
    }
