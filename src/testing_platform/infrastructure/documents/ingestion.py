"""只读输入、稳定身份、统一解析与显式失败。"""
from __future__ import annotations

import json
from pathlib import Path

from testing_platform.domain.documents import (
    DocumentIR, DocumentSegment, IngestionResult, IngestionSummary, InputFile, InputManifest, ParseIssue, SourceLocator,
    canonical_json, digest,
)

FORMATS = {".md": "markdown", ".markdown": "markdown", ".docx": "docx", ".pdf": "pdf"}
ADAPTER_VERSION = "1.0.0"


def create_manifest(paths: list[Path], *, role: str, config: dict | None = None) -> InputManifest:
    frozen_config = json.loads(canonical_json(config or {}))
    files, duplicates, seen = [], [], set()
    for path in paths:
        path = path.resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"输入不是文件：{path}")
        if path in seen:
            duplicates.append(str(path))
            continue
        seen.add(path)
        data = path.read_bytes()
        sha = digest(data)
        fmt = FORMATS.get(path.suffix.lower(), "unsupported")
        files.append(InputFile(document_id=f"doc-{sha}", path=str(path), name=path.name,
                               format=fmt, size_bytes=len(data), sha256=sha,
                               role=role, status="unsupported" if fmt == "unsupported" else "ready"))
    return InputManifest(schema_version="input-manifest/v1", files=files, config=frozen_config, config_sha256=digest(canonical_json(frozen_config)),
                         duplicate_paths=duplicates)


class IRBuilder:
    def __init__(self, source: InputFile):
        self.source = source
        self.segments: list[DocumentSegment] = []
        self.issues: list[ParseIssue] = []

    def add(self, kind: str, text: str, locator: SourceLocator, *, status="parsed",
            parent_id=None, heading_level=None, object_ref=None) -> str:
        content_hash = digest(text.encode("utf-8"))
        identity = [self.source.sha256, locator.model_dump(mode="json"), content_hash, kind, len(self.segments)]
        segment_id = f"seg-{digest(canonical_json(identity))}"
        self.segments.append(DocumentSegment(id=segment_id, kind=kind, text=text,
                                             order=len(self.segments), content_sha256=content_hash,
                                             locator=locator, status=status, parent_id=parent_id,
                                             heading_level=heading_level, object_ref=object_ref))
        return segment_id

    def issue(self, code: str, message: str, locator=None, segment_id=None):
        self.issues.append(ParseIssue(code=code, message=message, locator=locator, segment_id=segment_id))


def ingest(source: InputFile) -> DocumentIR:
    from testing_platform.infrastructure.documents.adapters import parse_docx, parse_markdown, parse_pdf

    builder = IRBuilder(source)
    parser_version = ADAPTER_VERSION
    if source.status == "unsupported":
        return DocumentIR(schema_version="document-ir/v1", source=source, parser="unsupported", parser_version=parser_version, status="unsupported",
                          issues=[ParseIssue(code="UNSUPPORTED_FORMAT", message="首期仅支持 DOCX、Markdown、PDF")])
    try:
        data = Path(source.path).read_bytes()
        if digest(data) != source.sha256 or len(data) != source.size_bytes:
            raise ValueError("冻结后原始输入发生变化")
        parser_version += "/" + {"markdown": parse_markdown, "docx": parse_docx, "pdf": parse_pdf}[source.format](data, builder)
    except Exception as exc:
        builder.issue("PARSE_FAILED", f"{type(exc).__name__}: {exc}")
    if not builder.segments and not builder.issues:
        builder.issue("EMPTY_DOCUMENT", "未取得内容，不能据此判断没有需求")
    status = "parsed" if not builder.issues else ("partial" if builder.segments else "failed")
    return DocumentIR(schema_version="document-ir/v1", source=source, parser=source.format, parser_version=parser_version,
                      status=status, segments=builder.segments, issues=builder.issues)


def ingest_manifest(manifest: InputManifest) -> IngestionResult:
    if digest(canonical_json(manifest.config)) != manifest.config_sha256:
        raise ValueError("运行配置与冻结哈希不符")
    documents = [ingest(source) for source in manifest.files]
    return IngestionResult(
        manifest_sha256=digest(canonical_json(manifest.model_dump(mode="json"))),
        config_sha256=manifest.config_sha256,
        documents=documents,
        summary=IngestionSummary(
            total=len(documents),
            parsed=sum(item.status == "parsed" for item in documents),
            partial=sum(item.status == "partial" for item in documents),
            failed=sum(item.status == "failed" for item in documents),
            unsupported=sum(item.status == "unsupported" for item in documents),
            issue_count=sum(len(item.issues) for item in documents),
        ),
    )
