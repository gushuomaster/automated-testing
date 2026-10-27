"""首期轻量 Adapter；不调用 OCR，不打开外部关系。"""
from __future__ import annotations

from importlib.metadata import version
from io import BytesIO

from docx import Document
from docx.oxml.ns import qn
from lxml import etree
from markdown_it import MarkdownIt

from testing_platform.domain.documents import SourceLocator
from testing_platform.infrastructure.documents.ingestion import IRBuilder


def parse_markdown(data: bytes, builder: IRBuilder) -> str:
    text = data.decode("utf-8-sig", errors="strict")
    lines = text.splitlines()
    tokens = MarkdownIt("commonmark", {"html": True}).enable("table").parse(text)
    stack: list[str] = []
    headings: list[tuple[int, str]] = []
    for token in tokens:
        if token.nesting == -1:
            closing = token.type.removesuffix("_close")
            if stack and stack[-1] == closing:
                stack.pop()
            continue
        parent = headings[-1][1] if headings else None
        if token.type == "inline" and token.map is not None:
            for child in token.children or []:
                if child.type not in {"image", "html_inline"}:
                    continue
                locator = SourceLocator(format="markdown", line_start=token.map[0] + 1,
                                        line_end=max(token.map[1], token.map[0] + 1))
                segment_id = builder.add("inline_object", child.content, locator, status="unknown",
                                         parent_id=parent, object_ref=child.attrGet("src"))
                builder.issue("MARKDOWN_OBJECT_UNPARSED", "图片或内联 HTML 未作语义解释", locator, segment_id)
            continue
        if token.nesting == 1:
            stack.append(token.type.removesuffix("_open"))
        if token.map is None:
            continue
        start, end = token.map
        locator = SourceLocator(format="markdown", line_start=start + 1, line_end=max(end, start + 1))
        kind = token.type.removesuffix("_open")
        inside_list_or_table = any(item in {"list_item", "table", "tr", "th", "td"} for item in stack[:-1])
        keep = (kind in {"heading", "list_item", "table", "fence", "code_block", "html_block", "hr"}
                or (kind == "paragraph" and not inside_list_or_table))
        if not keep:
            continue
        content = token.content if token.nesting == 0 else "\n".join(lines[start:end])
        if kind == "heading":
            level = int(token.tag[1:])
            while headings and headings[-1][0] >= level:
                headings.pop()
            parent = headings[-1][1] if headings else None
        else:
            level = None
        segment_id = builder.add(kind, content, locator, parent_id=parent,
                                 heading_level=level,
                                 status="unknown" if kind == "html_block" else "parsed")
        if kind == "heading":
            headings.append((level, segment_id))
        if kind == "html_block":
            builder.issue("MARKDOWN_HTML_UNPARSED", "原始 HTML 保留，未解释其显示内容", locator, segment_id)
    return f"markdown-it-py/{version('markdown-it-py')}"


def parse_docx(data: bytes, builder: IRBuilder) -> str:
    document = Document(BytesIO(data))
    style_names = {style.style_id: style.name for style in document.styles}

    def process_part(root, part):
        tree = root.getroottree()
        part_name = str(part.partname)

        def locate(element):
            return SourceLocator(format="docx", part=part_name, xpath=tree.getpath(element))

        def unknown(element, kind, text="", reference=None, parent=None):
            locator = locate(element)
            segment_id = builder.add(kind, text, locator, status="unknown", parent_id=parent, object_ref=reference)
            builder.issue("DOCX_OBJECT_UNPARSED", f"{kind} 未作语义解释", locator, segment_id)

        def walk(element, parent=None):
            tag = etree.QName(element).localname
            if tag == "p":
                text = "".join((node.text or "") if node.tag == qn("w:t") else
                               "\t" if node.tag == qn("w:tab") else "\n"
                               for node in element.iter() if node.tag in {qn("w:t"), qn("w:tab"), qn("w:br")})
                pstyle = element.find("./" + qn("w:pPr") + "/" + qn("w:pStyle"))
                name = style_names.get(pstyle.get(qn("w:val")), "") if pstyle is not None else ""
                level = int(name.split()[-1]) if name.lower().startswith("heading ") and name.split()[-1].isdigit() else None
                segment_id = builder.add("heading" if level else "paragraph", text, locate(element),
                                         parent_id=parent, heading_level=level, status="parsed" if text else "empty")
                for node in element.iter():
                    local = etree.QName(node).localname
                    if local in {"drawing", "pict", "object", "oMath", "oMathPara"}:
                        # 嵌套对象只在最外层登记，避免重复。
                        if any(etree.QName(a).localname in {"drawing", "pict", "object", "oMath", "oMathPara"}
                               for a in node.iterancestors() if a is not element):
                            continue
                        refs = []
                        for descendant in node.iter():
                            for key, value in descendant.attrib.items():
                                if key in {qn("r:embed"), qn("r:link"), qn("r:id")}:
                                    rel = part.rels.get(value)
                                    refs.append(f"{value}:{rel.target_ref if rel else 'unresolved'}")
                        unknown(node, local, "".join(node.itertext()), ";".join(refs) or None, segment_id)
                    elif local == "br" and node.get(qn("w:type")) == "page":
                        builder.add("explicit_page_break", "", locate(node), parent_id=segment_id)
                    elif local == "lastRenderedPageBreak":
                        builder.add("cached_page_break", "", locate(node), parent_id=segment_id, status="partial")
                    elif local in {"footnoteReference", "endnoteReference", "commentReference", "fldChar", "instrText"}:
                        unknown(node, local, node.text or "", parent=segment_id)
                if element.find("./" + qn("w:pPr") + "/" + qn("w:pageBreakBefore")) is not None:
                    builder.add("page_break_before", "", locate(element), parent_id=segment_id)
                return
            if tag in {"tbl", "tr", "tc"}:
                parent = builder.add({"tbl": "table", "tr": "table_row", "tc": "table_cell"}[tag],
                                     "", locate(element), parent_id=parent)
            if tag in {"altChunk", "subDoc"}:
                unknown(element, tag, reference=element.get(qn("r:id")), parent=parent)
                return
            for child in element:
                walk(child, parent)

        walk(root)

    process_part(document.element.body, document.part)
    for part in sorted(document.part.package.parts, key=lambda item: str(item.partname)):
        name = str(part.partname)
        if name.startswith(("/word/header", "/word/footer", "/word/footnotes", "/word/endnotes", "/word/comments")) and name.endswith(".xml"):
            root = etree.fromstring(part.blob, parser=etree.XMLParser(resolve_entities=False, no_network=True))
            process_part(root, part)
        for rel in sorted(part.rels.values(), key=lambda item: item.rId):
            if rel.is_external:
                locator = SourceLocator(format="docx", part=name, xpath=f"relationship:{rel.rId}")
                segment_id = builder.add("external_relationship", "", locator, status="unknown", object_ref=rel.target_ref)
                builder.issue("EXTERNAL_CONTENT_NOT_FETCHED", "外部关系仅登记，不访问其内容", locator, segment_id)
    builder.issue("DOCX_PAGINATION_LIMIT", "仅保留显式或缓存分页；未运行 Word 排版，不能提供可靠的渲染页码")
    return f"python-docx/{version('python-docx')}+lxml/{version('lxml')}"


def parse_pdf(data: bytes, builder: IRBuilder) -> str:
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted:
        builder.issue("PDF_ENCRYPTED", "加密 PDF 未解密，不猜测密码")
        return f"pypdf/{version('pypdf')}"
    for page_number, page in enumerate(reader.pages, 1):
        page_locator = SourceLocator(format="pdf", page=page_number)
        count = 0
        try:
            def visitor(text, cm, tm, font, size):
                nonlocal count
                if not text.strip():
                    return
                count += 1
                locator = SourceLocator(format="pdf", page=page_number, block=count - 1,
                                        x=tm[4] * cm[0] + tm[5] * cm[2] + cm[4],
                                        y=tm[4] * cm[1] + tm[5] * cm[3] + cm[5],
                                        text_matrix=list(tm), current_matrix=list(cm),
                                        coordinate_system=f"PDF user space; rotate={page.get('/Rotate', 0)}; mediabox={list(page.mediabox)}")
                uncertain = "\ufffd" in text or any(ord(c) < 32 and c not in "\t\r\n" for c in text)
                segment_id = builder.add("text_run", text, locator, status="partial" if uncertain else "parsed")
                if uncertain:
                    builder.issue("PDF_TEXT_ENCODING_UNCERTAIN", "文本含替换符或控制字符，不能保证中文保真", locator, segment_id)

            page.extract_text(visitor_text=visitor)
            # 页面图片和非文本区域单独登记，即使同页存在可提取文本。
            images = list(page.images)
            for image_index, image in enumerate(images):
                locator = SourceLocator(format="pdf", page=page_number, block=count + image_index)
                segment_id = builder.add("image", "", locator, status="unknown", object_ref=image.name)
                builder.issue("PDF_IMAGE_UNPARSED", "图像未启用 OCR 或语义解释", locator, segment_id)
            if not count:
                contents = page.get_contents()
                has_content = contents is not None and bool(contents.get_data().strip())
                kind = "unparsed_page" if has_content or images else "empty_page"
                segment_id = builder.add(kind, "", page_locator, status="unknown" if has_content or images else "empty")
                builder.issue("PDF_NO_TEXT_LAYER" if has_content or images else "PDF_EMPTY_PAGE",
                              "页面未取得文本；可能为扫描、图形或字体限制，不能判断没有需求" if has_content or images
                              else "页面内容流为空；空白状态显式登记", page_locator, segment_id)
        except Exception as exc:
            builder.issue("PDF_PAGE_FAILED", f"页面解析失败：{type(exc).__name__}: {exc}", page_locator)
    builder.issue("PDF_LAYOUT_LIMIT", "片段按 PDF 内容流顺序，坐标为文本起点；不保证多栏阅读顺序或表格结构，不是视觉边框")
    return f"pypdf/{version('pypdf')}"
