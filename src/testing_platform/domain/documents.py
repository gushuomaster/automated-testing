"""与解析库无关的输入清单和 Document IR 契约。"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceLocator(StrictModel):
    format: Literal["markdown", "docx", "pdf"]
    part: str | None = None
    block: int | None = Field(default=None, ge=0)
    xpath: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    page: int | None = Field(default=None, ge=1)
    x: float | None = None
    y: float | None = None
    coordinate_system: str | None = None
    text_matrix: list[float] | None = None
    current_matrix: list[float] | None = None

    @model_validator(mode="after")
    def validate_position(self):
        if self.format == "markdown" and (self.line_start is None or self.line_end is None
                                         or self.line_end < self.line_start):
            raise ValueError("Markdown 来源必须包含有效行范围")
        if self.format == "docx" and not (self.part and self.xpath):
            raise ValueError("DOCX 来源必须包含部件和 XPath")
        if self.format == "pdf" and self.page is None:
            raise ValueError("PDF 来源必须包含页码")
        return self


class InputFile(StrictModel):
    document_id: str
    path: str
    name: str
    format: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["ready", "unsupported"]
    role: Literal["construction", "calibration", "development", "regression", "formal"]


class InputManifest(StrictModel):
    schema_version: Literal["input-manifest/v1"]
    files: list[InputFile]
    config: dict = Field(default_factory=dict)
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duplicate_paths: list[str] = Field(default_factory=list)


class ParseIssue(StrictModel):
    code: str
    message: str
    locator: SourceLocator | None = None
    segment_id: str | None = None


class DocumentSegment(StrictModel):
    id: str
    kind: str
    order: int = Field(ge=0)
    text: str = ""
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: SourceLocator
    parent_id: str | None = None
    heading_level: int | None = None
    object_ref: str | None = None
    status: Literal["parsed", "partial", "unknown", "empty"] = "parsed"


class DocumentIR(StrictModel):
    schema_version: Literal["document-ir/v1"]
    source: InputFile
    parser: str
    parser_version: str
    status: Literal["parsed", "partial", "failed", "unsupported"]
    segments: list[DocumentSegment] = Field(default_factory=list)
    issues: list[ParseIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_structure(self):
        ids = [s.id for s in self.segments]
        if len(ids) != len(set(ids)) or [s.order for s in self.segments] != list(range(len(ids))):
            raise ValueError("片段编号必须唯一，顺序必须连续")
        if any(s.parent_id and s.parent_id not in ids for s in self.segments):
            raise ValueError("父片段不存在")
        return self


class IngestionSummary(StrictModel):
    total: int = Field(ge=0)
    parsed: int = Field(ge=0)
    partial: int = Field(ge=0)
    failed: int = Field(ge=0)
    unsupported: int = Field(ge=0)
    issue_count: int = Field(ge=0)


class IngestionResult(StrictModel):
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    documents: list[DocumentIR]
    summary: IngestionSummary

    @model_validator(mode="after")
    def validate_summary(self):
        actual = {status: sum(item.status == status for item in self.documents)
                  for status in ("parsed", "partial", "failed", "unsupported")}
        if (self.summary.total != len(self.documents)
                or any(getattr(self.summary, key) != value for key, value in actual.items())
                or self.summary.issue_count != sum(len(item.issues) for item in self.documents)):
            raise ValueError("摄取汇总与文档结果不一致")
        return self


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
