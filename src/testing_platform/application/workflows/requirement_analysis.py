"""Document IR → 候选 → 基线 → 双层核验；不生成测试用例。"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from pydantic import Field

from testing_platform.application.services.agent_exchange import build_agent_audit, export_agent_input
from testing_platform.domain.analysis import (
    RequirementBaseline, RequirementCandidate, RequirementReconciliation, VerificationFinding, VerificationResult,
)
from testing_platform.domain.documents import DocumentIR, InputManifest, StrictModel, canonical_json, digest
from testing_platform.domain.tasks import ArtifactKind, ArtifactReference
from testing_platform.domain.requirements import AnalysisIssue, ParsedRequirements
from testing_platform.infrastructure.hermes.schema_registry import resolve_output_schema
from testing_platform.infrastructure.hermes.skill_registry import SkillDefinition
from testing_platform.ports.agent_gateway import (
    AgentGateway, AgentInputPackage, AgentRequest, AgentResponse, AgentRunAudit,
    AgentRunStatus, AgentTaskType, OutputSchemaName,
)

FORBIDDEN_KEYS = {"plan", "cases", "test_cases", "test_items", "steps"}
NUMERIC_TOKEN = re.compile(r"(?<![\w.])(<=|>=|<|>|≤|≥)?\s*(\d+(?:\.\d+)?)\s*(ms|s|秒|毫秒|分钟|%|个|次|MB|GB|元|位|条)?", re.IGNORECASE)


class RequirementAnalysisRun(StrictModel):
    schema_version: str = "requirement-analysis-run/v1"
    prompt_versions: dict[str, str]
    input_manifest: InputManifest
    documents: list[DocumentIR]
    input_packages: list[AgentInputPackage]
    audits: list[AgentRunAudit]
    responses: list[dict] = Field(default_factory=list)
    candidates: list[RequirementCandidate]
    initial_baseline: RequirementBaseline
    deterministic_verifications: list[VerificationResult]
    semantic_verifications: list[VerificationResult]
    baseline_fragments: list[RequirementBaseline] = Field(default_factory=list)
    reconciliation: RequirementReconciliation | None = None
    revised_baseline: RequirementBaseline | None = None
    revision_count: int = Field(default=0, ge=0, le=1)

    @property
    def active_baseline(self) -> RequirementBaseline:
        return self.revised_baseline or self.initial_baseline

    def artifact_bundle(self) -> dict[str, object]:
        bundle = {
            "input-manifest.json": self.input_manifest.model_dump(mode="json"),
            "document-ir.json": [item.model_dump(mode="json") for item in self.documents],
            "parse-failures.json": [
                {"document_id": document.source.document_id, "issues": [issue.model_dump(mode="json") for issue in document.issues]}
                for document in self.documents if document.issues
            ],
            "input-packages.json": [item.model_dump(mode="json") for item in self.input_packages],
            "requirement-candidates.json": [item.model_dump(mode="json") for item in self.candidates],
            "requirement-baseline-initial.json": self.initial_baseline.model_dump(mode="json"),
            "deterministic-verification.json": [item.model_dump(mode="json") for item in self.deterministic_verifications],
            "semantic-verification.json": [item.model_dump(mode="json") for item in self.semantic_verifications],
            "agent-audits.json": [item.model_dump(mode="json") for item in self.audits],
            "agent-responses.json": self.responses,
            "ambiguities.json": [item.model_dump(mode="json") for item in self.active_baseline.parsed.ambiguities],
            "conflicts.json": [item.model_dump(mode="json") for item in self.active_baseline.parsed.conflicts],
            "test-type-recommendations.json": [item.model_dump(mode="json") for item in self.active_baseline.parsed.recommendations],
            "trace-index.json": self.active_baseline.parsed.trace_index,
        }
        if self.baseline_fragments:
            bundle["requirement-baseline-fragments.json"] = [
                item.model_dump(mode="json") for item in self.baseline_fragments
            ]
        if self.reconciliation:
            bundle["requirement-reconciliation.json"] = self.reconciliation.model_dump(mode="json")
        if self.revised_baseline:
            bundle["requirement-baseline-revised.json"] = self.revised_baseline.model_dump(mode="json")
        _reject_forbidden_keys(bundle)
        return bundle


class AgentStepFailure(RuntimeError):
    def __init__(self, stage: str, package: AgentInputPackage, audit: AgentRunAudit, cause: Exception):
        super().__init__(f"{stage}: {cause}")
        self.stage, self.package, self.audit, self.cause = stage, package, audit, cause


class CandidateSourceValidationError(ValueError):
    def __init__(self, code: str, owner_type: str, owner_id: str, segment_id: str):
        self.code = code
        self.owner_type = owner_type
        self.owner_id = owner_id
        self.segment_id = segment_id
        if code == "SOURCE_SEGMENT_OUTSIDE_WINDOW":
            message = f"{owner_id}: 候选引用了当前窗口以外的片段"
        elif code == "SOURCE_EXCERPT_MISMATCH":
            message = f"{owner_id}: 候选摘录不是输入片段的连续原文"
        else:
            message = f"{owner_id}: 候选引用了不存在的片段"
        super().__init__(message)

    def as_payload(self) -> dict[str, str]:
        return {
            "code": self.code,
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "segment_id": self.segment_id,
            "message": str(self),
        }


class AgentInputLimitExceeded(RuntimeError):
    def __init__(self, stage: str, actual_chars: int, limit_chars: int) -> None:
        super().__init__(f"阶段 {stage} 输入为 {actual_chars} 字符，超过上限 {limit_chars}")
        self.stage, self.actual_chars, self.limit_chars = stage, actual_chars, limit_chars


def _candidate_segment_ids(candidates: list[RequirementCandidate]) -> set[str]:
    references = [reference for candidate in candidates
                  for item in [*candidate.requirements, *candidate.ambiguities]
                  for reference in item.source_evidence]
    return {reference.segment_id for reference in references if reference.segment_id}


def _baseline_segment_ids(baseline: RequirementBaseline) -> set[str]:
    parsed = baseline.parsed
    references = []
    for item in [*parsed.requirements, *parsed.ambiguities, *parsed.conflicts]:
        references.extend(item.source_evidence)
    return {reference.segment_id for reference in references if reference.segment_id}


def _source_projection(segment_ids: set[str], documents: list[DocumentIR]) -> list[dict]:
    owners = {segment.id for document in documents for segment in document.segments}
    missing = segment_ids - owners
    if missing:
        raise ValueError(f"来源投影引用不存在的片段：{sorted(missing)}")
    projection = []
    for document in documents:
        segments = [segment.model_dump(mode="json", include={"id", "order", "text", "locator"},
                                       exclude_none=True, exclude_defaults=True)
                    for segment in document.segments if segment.id in segment_ids]
        if segments:
            projection.append({
                "document": document.source.model_dump(mode="json",
                                                        include={"document_id", "path", "sha256", "format"},
                                                        exclude_none=True, exclude_defaults=True),
                "segments": segments,
            })
    return projection


def _without_source_excerpts(value: object) -> object:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_defaults=True)
    if isinstance(value, dict):
        return {
            key: ([{field: item for field, item in reference.items() if field != "excerpt"}
                   if isinstance(reference, dict) else reference for reference in item]
                  if key == "source_evidence" and isinstance(item, list)
                  else _without_source_excerpts(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_without_source_excerpts(item) for item in value]
    return value


def _reject_forbidden_keys(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_KEYS:
                raise ValueError(f"正式需求分析产物包含禁止字段：{path}.{key}")
            _reject_forbidden_keys(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_forbidden_keys(item, f"{path}[{index}]")


def _fidelity_tokens(text: str) -> set[tuple[str, ...]]:
    tokens = {("number", m.group(1) or "", m.group(2), (m.group(3) or "").lower())
              for m in NUMERIC_TOKEN.finditer(text)}
    tokens |= {("range", *m.groups()) for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(至|到|-|~)\s*(\d+(?:\.\d+)?)", text)}
    tokens |= {("relation", term) for term in ("包含边界", "不包含边界", "大于", "小于", "不低于", "不高于", "至少", "最多") if term in text}
    return tokens


def normalize_baseline_fragment(baseline: RequirementBaseline, chunk_index: int) -> RequirementBaseline:
    normalized = baseline.model_copy(deep=True)
    parsed = normalized.parsed
    mapping = {
        item.id: f"REQ-C{chunk_index:02d}-{index:03d}"
        for index, item in enumerate(parsed.requirements, start=1)
    }
    for item in parsed.requirements:
        item.id = mapping[item.id]
    for prefix, collection in (("AMB", parsed.ambiguities), ("CON", parsed.conflicts)):
        for index, item in enumerate(collection, start=1):
            item.id = f"{prefix}-C{chunk_index:02d}-{index:03d}"
            item.requirement_ids = [mapping[identifier] for identifier in item.requirement_ids]
    for item in parsed.recommendations:
        item.requirement_ids = [mapping[identifier] for identifier in item.requirement_ids]
    for item in parsed.unresolved_fields:
        if item.requirement_id:
            item.requirement_id = mapping[item.requirement_id]
    parsed.trace_index = {mapping[identifier]: values for identifier, values in parsed.trace_index.items()}
    return RequirementBaseline.model_validate(normalized.model_dump(mode="json"))


def assemble_baseline_fragments(fragments: list[RequirementBaseline]) -> RequirementBaseline:
    if not fragments:
        raise ValueError("至少需要一个归并片段")
    documents, seen_documents = [], set()
    for fragment in fragments:
        for document in [fragment.parsed.source, *fragment.parsed.additional_sources]:
            key = (document.path, document.sha256)
            if key not in seen_documents:
                documents.append(document.model_copy(deep=True)); seen_documents.add(key)
    parsed = ParsedRequirements(
        schema_version="2.0",
        source=documents[0],
        additional_sources=documents[1:],
        requirements=[item.model_copy(deep=True) for fragment in fragments for item in fragment.parsed.requirements],
        unresolved_fields=[item.model_copy(deep=True) for fragment in fragments for item in fragment.parsed.unresolved_fields],
        warnings=[item for fragment in fragments for item in fragment.parsed.warnings],
        ambiguities=[item.model_copy(deep=True) for fragment in fragments for item in fragment.parsed.ambiguities],
        conflicts=[item.model_copy(deep=True) for fragment in fragments for item in fragment.parsed.conflicts],
        recommendations=[item.model_copy(deep=True) for fragment in fragments for item in fragment.parsed.recommendations],
        failed_segments=list(dict.fromkeys(item for fragment in fragments for item in fragment.parsed.failed_segments)),
        trace_index={key: list(value) for fragment in fragments for key, value in fragment.parsed.trace_index.items()},
    )
    return RequirementBaseline(schema_version="requirement-baseline/v1", parsed=parsed)


def validate_reconciliation(reconciliation: RequirementReconciliation, baseline: RequirementBaseline) -> None:
    requirements = {item.id: item for item in baseline.parsed.requirements}
    known = set(requirements)
    consumed: set[str] = set()
    conflict_pairs = [set(item.requirement_ids) for item in baseline.parsed.conflicts]
    for merge in reconciliation.merges:
        members = set(merge.requirement_ids)
        if not members <= known:
            raise ValueError("跨块合并引用了未知需求")
        if members & consumed:
            raise ValueError("同一需求不能参与多个跨块合并")
        if any(pair <= members for pair in conflict_pairs):
            raise ValueError("已知冲突需求不能跨块合并")
        signatures = {
            frozenset(_fidelity_tokens("\n".join([
                requirements[identifier].description,
                requirements[identifier].expected_behavior,
                *requirements[identifier].conditions,
            ])))
            for identifier in members
        }
        if len(signatures) > 1:
            raise ValueError("数值、单位或边界不同的需求不能跨块合并")
        consumed.update(members)
    for relation in [*reconciliation.conflicts, *reconciliation.ambiguities]:
        if not set(relation.requirement_ids) <= known:
            raise ValueError("跨块关系引用了未知需求")


def apply_reconciliation(
    baseline: RequirementBaseline,
    reconciliation: RequirementReconciliation,
) -> RequirementBaseline:
    validate_reconciliation(reconciliation, baseline)
    parsed = baseline.parsed.model_copy(deep=True)
    requirements = {item.id: item for item in parsed.requirements}
    replacement = {identifier: merge.retained_id for merge in reconciliation.merges
                   for identifier in merge.requirement_ids}
    merged_items = {}
    for merge in reconciliation.merges:
        retained = requirements[merge.retained_id].model_copy(deep=True)
        sources, seen = [], set()
        for identifier in merge.requirement_ids:
            for source in requirements[identifier].source_evidence:
                key = canonical_json(source.model_dump(mode="json"))
                if key not in seen:
                    sources.append(source.model_copy(deep=True)); seen.add(key)
        retained.source_evidence = sources
        merged_items[merge.retained_id] = retained
    emitted, final_requirements = set(), []
    for item in parsed.requirements:
        target = replacement.get(item.id)
        if target:
            if target not in emitted:
                final_requirements.append(merged_items[target]); emitted.add(target)
        else:
            final_requirements.append(item)
    parsed.requirements = final_requirements

    def mapped_ids(values: list[str]) -> list[str]:
        return list(dict.fromkeys(replacement.get(value, value) for value in values))

    for collection in (parsed.ambiguities, parsed.conflicts):
        for item in collection:
            item.requirement_ids = mapped_ids(item.requirement_ids)
    for item in parsed.recommendations:
        item.requirement_ids = mapped_ids(item.requirement_ids)
    for item in parsed.unresolved_fields:
        if item.requirement_id:
            item.requirement_id = replacement.get(item.requirement_id, item.requirement_id)

    final_by_id = {item.id: item for item in parsed.requirements}
    for kind, relations in (("CON-X", reconciliation.conflicts), ("AMB-X", reconciliation.ambiguities)):
        target = parsed.conflicts if kind.startswith("CON") else parsed.ambiguities
        for index, relation in enumerate(relations, start=1):
            ids = mapped_ids(relation.requirement_ids)
            sources, seen = [], set()
            for identifier in ids:
                for source in final_by_id[identifier].source_evidence:
                    key = canonical_json(source.model_dump(mode="json"))
                    if key not in seen:
                        sources.append(source.model_copy(deep=True)); seen.add(key)
            target.append(AnalysisIssue(id=f"{kind}-{index:03d}", description=relation.description,
                                        impact=relation.impact, requirement_ids=ids, source_evidence=sources))
    parsed.trace_index = {
        item.id: list(dict.fromkeys(source.segment_id for source in item.source_evidence if source.segment_id))
        for item in parsed.requirements
    }
    return RequirementBaseline(schema_version="requirement-baseline/v1", parsed=parsed)


def baseline_subset(baseline: RequirementBaseline, requirement_ids: list[str]) -> RequirementBaseline:
    wanted = set(requirement_ids)
    parsed = baseline.parsed
    subset = ParsedRequirements(
        schema_version="2.0",
        source=parsed.source.model_copy(deep=True),
        additional_sources=[item.model_copy(deep=True) for item in parsed.additional_sources],
        requirements=[item.model_copy(deep=True) for item in parsed.requirements if item.id in wanted],
        unresolved_fields=[item.model_copy(deep=True) for item in parsed.unresolved_fields
                           if not item.requirement_id or item.requirement_id in wanted],
        warnings=list(parsed.warnings),
        failed_segments=list(parsed.failed_segments),
        trace_index={key: list(value) for key, value in parsed.trace_index.items() if key in wanted},
    )
    return RequirementBaseline(schema_version="requirement-baseline/v1", parsed=subset)


def reconciliation_summary(baseline: RequirementBaseline) -> list[dict]:
    return [{
        "id": item.id,
        "target": item.target,
        "categories": item.categories,
        "description": item.description,
        "conditions": item.conditions,
        "expected_behavior": item.expected_behavior,
        "information_nature": item.information_nature,
        "confidence": item.confidence,
        "segment_ids": [source.segment_id for source in item.source_evidence if source.segment_id],
    } for item in baseline.parsed.requirements]


def validate_semantic_chunk(
    result: VerificationResult,
    baseline_sha256: str,
    requirement_ids: list[str],
) -> None:
    expected = set(requirement_ids)
    actual = {item.requirement_id for item in result.findings}
    if result.method != "semantic" or result.baseline_sha256 != baseline_sha256:
        raise ValueError("分块语义核验方法或完整基线哈希不一致")
    if actual != expected or len(actual) != len(result.findings):
        raise ValueError("分块语义核验必须恰好覆盖本块每条需求")


def deterministic_verify(baseline: RequirementBaseline, documents: list[DocumentIR]) -> VerificationResult:
    segments = {segment.id: segment for document in documents for segment in document.segments}
    owners = {segment.id: document.source for document in documents for segment in document.segments}
    failed = {issue.segment_id for document in documents for issue in document.issues if issue.segment_id}
    findings: list[VerificationFinding] = []
    seen: dict[tuple, str] = {}
    for requirement in baseline.parsed.requirements:
        source_ids = [ref.segment_id for ref in requirement.source_evidence if ref.segment_id]
        for ref in requirement.source_evidence:
            if ref.segment_id not in segments:
                continue
            segment, source = segments[ref.segment_id], owners[ref.segment_id]
            if (ref.path != source.path or ref.sha256 != source.sha256 or ref.locator != segment.locator
                    or (ref.excerpt is not None and ref.excerpt not in segment.text)):
                findings.append(VerificationFinding(requirement_id=requirement.id, status="unsupported",
                                                     code="SOURCE_REFERENCE_MISMATCH", message="来源文件、哈希、位置或摘录与片段不一致",
                                                     segment_ids=[segment.id]))
        missing = [sid for sid in source_ids if sid not in segments]
        if missing:
            findings.append(VerificationFinding(requirement_id=requirement.id, status="unsupported",
                                                code="SOURCE_SEGMENT_MISSING", message="来源片段不存在", segment_ids=missing))
        unavailable = [sid for sid in source_ids if sid in failed or (sid in segments and segments[sid].status not in {"parsed", "partial"})]
        if unavailable:
            findings.append(VerificationFinding(requirement_id=requirement.id, status="indeterminate",
                                                code="FAILED_SEGMENT_REFERENCE", message="需求引用了未解析或未知片段", segment_ids=unavailable))
        source_text = "\n".join(segments[sid].text for sid in source_ids if sid in segments)
        output_text = "\n".join([requirement.description, requirement.expected_behavior, *requirement.conditions,
                                  *requirement.acceptance_criteria, *requirement.constraints])
        extra_numbers = _fidelity_tokens(output_text) - _fidelity_tokens(source_text)
        if extra_numbers:
            findings.append(VerificationFinding(requirement_id=requirement.id, status="unsupported",
                                                code="NUMERIC_FIDELITY_ERROR",
                                                message=f"输出中的数值/单位/比较符不受来源支持：{sorted(extra_numbers)}",
                                                segment_ids=source_ids))
        key = (requirement.target.strip().casefold(), requirement.description.strip().casefold(),
               tuple(sorted(item.strip().casefold() for item in requirement.conditions)))
        if key in seen:
            findings.append(VerificationFinding(requirement_id=requirement.id, status="partially_supported",
                                                code="DUPLICATE_REQUIREMENT", message=f"与 {seen[key]} 重复", segment_ids=source_ids))
        else:
            seen[key] = requirement.id
        indexed = set(baseline.parsed.trace_index.get(requirement.id, []))
        if indexed != set(source_ids):
            findings.append(VerificationFinding(requirement_id=requirement.id, status="partially_supported",
                                                code="TRACE_INDEX_MISMATCH", message="追溯索引与来源引用不一致", segment_ids=source_ids))
    payload = baseline.model_dump(mode="json")
    return VerificationResult(schema_version="verification-result/v1", baseline_sha256=digest(canonical_json(payload)),
                              method="deterministic", findings=findings)


def validate_consolidation(baseline: RequirementBaseline, candidates: list[RequirementCandidate], documents: list[DocumentIR]) -> None:
    document_segments = {segment.id for document in documents for segment in document.segments}
    candidate_segments = {ref.segment_id for candidate in candidates for requirement in candidate.requirements
                          for ref in requirement.source_evidence if ref.segment_id}
    for requirement in baseline.parsed.requirements:
        sources = {ref.segment_id for ref in requirement.source_evidence if ref.segment_id}
        if not sources or not sources <= document_segments or not sources <= candidate_segments:
            raise ValueError(f"{requirement.id}: 归并结果引入了候选以外的来源")
    requirement_ids = {item.id for item in baseline.parsed.requirements}
    for conflict in baseline.parsed.conflicts:
        if len(set(conflict.requirement_ids)) < 2 or not set(conflict.requirement_ids) <= requirement_ids:
            raise ValueError(f"{conflict.id}: 冲突必须保留至少两条有效需求")
        source_ids = {ref.segment_id for ref in conflict.source_evidence if ref.segment_id}
        expected_ids = {ref.segment_id for requirement in baseline.parsed.requirements
                        if requirement.id in conflict.requirement_ids for ref in requirement.source_evidence if ref.segment_id}
        if not expected_ids <= source_ids:
            raise ValueError(f"{conflict.id}: 冲突没有保留双方来源")


def _candidate_source_references(candidate: RequirementCandidate):
    for requirement in candidate.requirements:
        for ref in requirement.source_evidence:
            yield "requirement", requirement.id, ref
    for ambiguity in candidate.ambiguities:
        for ref in ambiguity.source_evidence:
            yield "ambiguity", ambiguity.id, ref


def canonicalize_candidate_sources(
    candidate: RequirementCandidate,
    documents: list[DocumentIR],
    *,
    allowed_segment_ids: set[str] | None = None,
) -> tuple[RequirementCandidate, list[dict]]:
    """以 segment_id 为权威键补正模型机械复制的来源元数据，保留可审计变更。"""
    normalized = candidate.model_copy(deep=True)
    segments = {segment.id: (segment, document.source) for document in documents for segment in document.segments}
    changes: list[dict] = []
    for owner_type, owner_id, ref in _candidate_source_references(normalized):
        segment_id = ref.segment_id or ""
        pair = segments.get(segment_id)
        if allowed_segment_ids is not None and segment_id not in allowed_segment_ids:
            code = "SOURCE_SEGMENT_OUTSIDE_WINDOW" if pair is not None else "SOURCE_SEGMENT_MISSING"
            raise CandidateSourceValidationError(code, owner_type, owner_id, segment_id)
        if pair is None:
            raise CandidateSourceValidationError("SOURCE_SEGMENT_MISSING", owner_type, owner_id, segment_id)
        segment, source = pair
        if ref.excerpt is not None and ref.excerpt not in segment.text:
            raise CandidateSourceValidationError(
                "SOURCE_EXCERPT_MISMATCH", owner_type, owner_id, segment_id,
            )
        mismatches = []
        if ref.path != source.path:
            mismatches.append("path")
        if ref.sha256 != source.sha256:
            mismatches.append("sha256")
        if ref.locator != segment.locator:
            mismatches.append("locator")
        if mismatches:
            changes.append({"owner_type": owner_type, "owner_id": owner_id,
                            "segment_id": segment.id, "fields": mismatches})
            ref.path = source.path
            ref.sha256 = source.sha256
            ref.locator = segment.locator.model_copy(deep=True)
    validate_candidate_sources(normalized, documents)
    return normalized, changes


def validate_source_repair_preserves_candidate(
    original: RequirementCandidate,
    repaired: RequirementCandidate,
) -> None:
    """来源修复只能修改来源引用，不能改变候选语义、顺序或数量。"""
    comparable = []
    for candidate in (original, repaired):
        payload = candidate.model_dump(mode="json")
        for collection in ("requirements", "ambiguities"):
            for item in payload.get(collection, []):
                item.pop("source_evidence", None)
        comparable.append(payload)
    if comparable[0] != comparable[1]:
        raise ValueError("来源修复不得修改、删除或重排候选内容")


def validate_candidate_sources(candidate: RequirementCandidate, documents: list[DocumentIR]) -> None:
    segments = {segment.id: (segment, document.source) for document in documents for segment in document.segments}
    for _, owner_id, ref in _candidate_source_references(candidate):
        pair = segments.get(ref.segment_id or "")
        if pair is None:
            raise ValueError(f"{owner_id}: 候选引用了不存在的片段")
        segment, source = pair
        if (ref.path != source.path or ref.sha256 != source.sha256 or ref.locator != segment.locator
                or (ref.excerpt is not None and ref.excerpt not in segment.text)):
            raise ValueError(f"{owner_id}: 候选来源元数据不是输入片段的原值")


def persist_requirement_analysis_run(run: RequirementAnalysisRun, store, task_id: UUID) -> list[ArtifactReference]:
    references = []
    for name, payload in run.artifact_bundle().items():
        kind = ArtifactKind.INPUT if name in {"input-manifest.json", "document-ir.json"} else ArtifactKind.REQUIREMENT_ANALYSIS
        references.append(store.put_json(task_id, name, payload, kind))
    return references


def validate_semantic_result(result: VerificationResult, baseline: RequirementBaseline) -> None:
    expected_hash = digest(canonical_json(baseline.model_dump(mode="json")))
    expected_ids = {item.id for item in baseline.parsed.requirements}
    actual_ids = {item.requirement_id for item in result.findings}
    if result.method != "semantic" or result.baseline_sha256 != expected_hash:
        raise ValueError("语义核验方法或基线哈希不一致")
    if actual_ids != expected_ids or len(actual_ids) != len(result.findings):
        raise ValueError("语义核验必须覆盖每条需求，且不能引用未知需求")


def _read_prompt(root: Path, name: str) -> tuple[str, str]:
    path = root / name
    content = path.read_text(encoding="utf-8")
    return content, digest(content.encode("utf-8"))


def _structured(response: AgentResponse, schema: OutputSchemaName):
    if response.status != AgentRunStatus.SUCCEEDED:
        raise RuntimeError(response.error.message if response.error else "Agent 未成功返回")
    payload = response.structured_output
    if payload is None:
        payload = json.loads(response.content)
    _reject_forbidden_keys(payload)
    return resolve_output_schema(schema).model_validate(payload)


class RequirementAnalysisWorkflow:
    def __init__(self, gateway_factory: Callable[[str], AgentGateway], skill: SkillDefinition,
                 prompt_root: Path = Path("prompts/requirement-analysis"), max_window_chars: int = 12000,
                 max_window_segments: int = 12, event_sink: Callable[[str, dict], None] | None = None,
                 max_agent_input_chars: int = 450_000, max_consolidation_candidates: int = 2,
                 max_verification_requirements: int = 40) -> None:
        self.gateway_factory, self.skill, self.prompt_root = gateway_factory, skill, prompt_root
        self.max_window_chars = max_window_chars
        self.max_window_segments = max_window_segments
        self.skill_text = (skill.path / "SKILL.md").read_text(encoding="utf-8")
        self.event_sink = event_sink
        self.max_agent_input_chars = max_agent_input_chars
        if max_consolidation_candidates <= 0 or max_verification_requirements <= 0:
            raise ValueError("分块上限必须大于零")
        self.max_consolidation_candidates = max_consolidation_candidates
        self.max_verification_requirements = max_verification_requirements
        self.responses: list[dict] = []

    def _call(self, stage: str, task_type: AgentTaskType, schema: OutputSchemaName, prompt: str,
              payload: object, records: tuple[list, list], attempt: int = 1):
        inputs, audits = records
        schema_text = json.dumps(resolve_output_schema(schema).model_json_schema(), ensure_ascii=False, separators=(",", ":"))
        request = AgentRequest(task_type=task_type,
                               user_input=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                               system_context=self.skill_text + "\n\n" + prompt + "\n\n输出必须通过以下 JSON Schema：\n" + schema_text,
                               skill_name=self.skill.name, skill_version=self.skill.version,
                               output_schema=schema, model_id="runtime-configured",
                               parameters={"stage": stage}, attempt=attempt)
        package = export_agent_input(request)
        inputs.append(package)
        if self.event_sink:
            self.event_sink(stage + "-input", package.model_dump(mode="json"))
        input_chars = len(request.user_input) + len(request.system_context or "")
        if input_chars > self.max_agent_input_chars:
            rejection = {"stage": stage, "actual_chars": input_chars, "limit_chars": self.max_agent_input_chars}
            if self.event_sink:
                self.event_sink(stage + "-input-rejected", rejection)
            raise AgentInputLimitExceeded(stage, input_chars, self.max_agent_input_chars)
        try:
            response = self.gateway_factory(stage).run(request)
        except Exception as exc:
            if self.event_sink:
                self.event_sink(stage + "-exception", {"type": type(exc).__name__, "message": str(exc)})
            raise
        audit = build_agent_audit(request, response)
        audits.append(audit)
        from testing_platform.application.services.agent_exchange import _hashable
        raw = response.raw_response if response.raw_response is not None else response.content
        snapshot = {"stage": stage, "audit": audit.model_dump(mode="json"),
                    "content": response.content, "raw_response": json.loads(_hashable(raw))}
        self.responses.append(snapshot)
        if self.event_sink:
            self.event_sink(stage + "-response", snapshot)
        try:
            return _structured(response, schema)
        except Exception as exc:
            raise AgentStepFailure(stage, package, audit, exc) from exc

    def _windows(self, documents: list[DocumentIR]) -> list[dict]:
        windows, current, size = [], [], 0
        for document in documents:
            for segment in document.segments:
                if segment.status not in {"parsed", "partial"} or not segment.text.strip():
                    continue
                item = {"document": document.source.model_dump(mode="json"),
                        "segment": segment.model_dump(mode="json", exclude_none=True, exclude_defaults=True)}
                item_size = len(canonical_json(item))
                if current and (size + item_size > self.max_window_chars or len(current) >= self.max_window_segments):
                    windows.append({"segments": current}); current, size = [], 0
                current.append(item); size += item_size
        if current: windows.append({"segments": current})
        return windows

    def _consolidate(
        self,
        candidates: list[RequirementCandidate],
        documents: list[DocumentIR],
        prompts: dict[str, tuple[str, str]],
        records: tuple[list, list],
    ) -> tuple[RequirementBaseline, list[RequirementBaseline], RequirementReconciliation | None]:
        if len(candidates) <= self.max_consolidation_candidates:
            source_context = _source_projection(_candidate_segment_ids(candidates), documents)
            initial = self._call(
                "consolidate", AgentTaskType.REQUIREMENT_ANALYSIS,
                OutputSchemaName.REQUIREMENT_BASELINE, prompts["consolidator-v1.md"][0],
                {"candidates": _without_source_excerpts(candidates), "sources": source_context}, records,
            )
            validate_consolidation(initial, candidates, documents)
            return initial, [], None

        fragments = []
        for index in range(0, len(candidates), self.max_consolidation_candidates):
            chunk = candidates[index:index + self.max_consolidation_candidates]
            chunk_index = index // self.max_consolidation_candidates
            stage = f"consolidate-{chunk_index}"
            fragment = self._call(
                stage, AgentTaskType.REQUIREMENT_ANALYSIS,
                OutputSchemaName.REQUIREMENT_BASELINE, prompts["consolidator-fragment-v1.md"][0],
                {"candidates": _without_source_excerpts(chunk),
                 "sources": _source_projection(_candidate_segment_ids(chunk), documents)}, records,
            )
            try:
                validate_consolidation(fragment, chunk, documents)
                fragment = normalize_baseline_fragment(fragment, chunk_index)
            except Exception as exc:
                raise AgentStepFailure(stage, records[0][-1], records[1][-1], exc) from exc
            fragments.append(fragment)

        assembled = assemble_baseline_fragments(fragments)
        reconciliation = self._call(
            "reconcile", AgentTaskType.REQUIREMENT_RECONCILIATION,
            OutputSchemaName.REQUIREMENT_RECONCILIATION, prompts["reconciliation-v1.md"][0],
            {"requirements": reconciliation_summary(assembled)}, records,
        )
        try:
            initial = apply_reconciliation(assembled, reconciliation)
            validate_consolidation(initial, candidates, documents)
        except Exception as exc:
            raise AgentStepFailure("reconcile", records[0][-1], records[1][-1], exc) from exc
        return initial, fragments, reconciliation

    def _semantic_verify(
        self,
        baseline: RequirementBaseline,
        documents: list[DocumentIR],
        prompt: str,
        records: tuple[list, list],
    ) -> VerificationResult:
        expected_hash = digest(canonical_json(baseline.model_dump(mode="json")))
        requirements = baseline.parsed.requirements
        if len(requirements) <= self.max_verification_requirements:
            result = self._call(
                "verify", AgentTaskType.REQUIREMENT_VERIFICATION,
                OutputSchemaName.VERIFICATION_RESULT, prompt,
                {"baseline_sha256": expected_hash, "baseline": _without_source_excerpts(baseline),
                 "sources": _source_projection(_baseline_segment_ids(baseline), documents)}, records,
            )
            validate_semantic_result(result, baseline)
            return result

        findings = []
        for index in range(0, len(requirements), self.max_verification_requirements):
            chunk = requirements[index:index + self.max_verification_requirements]
            ids = [item.id for item in chunk]
            subset = baseline_subset(baseline, ids)
            stage = f"verify-{index // self.max_verification_requirements}"
            result = self._call(
                stage, AgentTaskType.REQUIREMENT_VERIFICATION,
                OutputSchemaName.VERIFICATION_RESULT, prompt,
                {"baseline_sha256": expected_hash, "baseline": _without_source_excerpts(subset),
                 "sources": _source_projection(_baseline_segment_ids(subset), documents)}, records,
            )
            try:
                validate_semantic_chunk(result, expected_hash, ids)
            except Exception as exc:
                raise AgentStepFailure(stage, records[0][-1], records[1][-1], exc) from exc
            findings.extend(result.findings)
        combined = VerificationResult(schema_version="verification-result/v1", baseline_sha256=expected_hash,
                                      method="semantic", findings=findings)
        validate_semantic_result(combined, baseline)
        return combined

    def run(self, documents: list[DocumentIR], manifest: InputManifest, *, allow_revision: bool = True) -> RequirementAnalysisRun:
        self.responses = []
        windows = self._windows(documents)
        if not documents or not windows:
            raise ValueError("没有可供需求分析的已解析文本片段")
        expected_sources = {(item.document_id, item.sha256) for item in manifest.files}
        actual_sources = {(item.source.document_id, item.source.sha256) for item in documents}
        if expected_sources != actual_sources:
            raise ValueError("Document IR 与输入清单不一致")
        prompts = {}
        for name in ("section-extractor-v1.md", "source-repair-v1.md", "consolidator-v1.md",
                     "consolidator-fragment-v1.md", "reconciliation-v1.md",
                     "semantic-verifier-v1.md", "repair-v1.md"):
            prompts[name] = _read_prompt(self.prompt_root, name)
        inputs, audits, candidates = [], [], []
        for index, window in enumerate(windows):
            stage = f"extract-{index}"
            candidate = self._call(stage, AgentTaskType.REQUIREMENT_ANALYSIS,
                                   OutputSchemaName.REQUIREMENT_CANDIDATE, prompts["section-extractor-v1.md"][0],
                                   window, (inputs, audits))
            allowed_segment_ids = {item["segment"]["id"] for item in window["segments"]}
            try:
                candidate, source_changes = canonicalize_candidate_sources(
                    candidate, documents, allowed_segment_ids=allowed_segment_ids,
                )
                if source_changes and self.event_sink:
                    self.event_sink(stage + "-source-normalization", {"changes": source_changes})
            except CandidateSourceValidationError as source_error:
                if self.event_sink:
                    self.event_sink(stage + "-source-validation-error", source_error.as_payload())
                repair_stage = stage + "-source-repair"
                repaired = self._call(
                    repair_stage,
                    AgentTaskType.REQUIREMENT_SOURCE_REPAIR,
                    OutputSchemaName.REQUIREMENT_CANDIDATE,
                    prompts["source-repair-v1.md"][0],
                    {
                        "original_candidate": candidate.model_dump(mode="json"),
                        "validation_error": source_error.as_payload(),
                        "valid_segments": [
                            {"segment_id": item["segment"]["id"], "text": item["segment"]["text"]}
                            for item in window["segments"]
                        ],
                    },
                    (inputs, audits),
                    attempt=2,
                )
                try:
                    validate_source_repair_preserves_candidate(candidate, repaired)
                    candidate, source_changes = canonicalize_candidate_sources(
                        repaired, documents, allowed_segment_ids=allowed_segment_ids,
                    )
                    if source_changes and self.event_sink:
                        self.event_sink(repair_stage + "-source-normalization", {"changes": source_changes})
                except Exception as exc:
                    raise AgentStepFailure(repair_stage, inputs[-1], audits[-1], exc) from exc
            except Exception as exc:
                raise AgentStepFailure(stage, inputs[-1], audits[-1], exc) from exc
            candidates.append(candidate)
        try:
            initial, fragments, reconciliation = self._consolidate(candidates, documents, prompts, (inputs, audits))
        except Exception as exc:
            if isinstance(exc, AgentStepFailure):
                raise
            raise AgentStepFailure("consolidate", inputs[-1], audits[-1], exc) from exc
        det = deterministic_verify(initial, documents)
        try:
            semantic = self._semantic_verify(
                initial, documents, prompts["semantic-verifier-v1.md"][0], (inputs, audits)
            )
        except Exception as exc:
            if isinstance(exc, AgentStepFailure):
                raise
            raise AgentStepFailure("verify", inputs[-1], audits[-1], exc) from exc
        revised, revision_count = None, 0
        problems = det.findings + [f for f in semantic.findings if f.status != "supported"]
        deterministic_results, semantic_results = [det], [semantic]
        if allow_revision and problems:
            if len(initial.parsed.requirements) > self.max_verification_requirements:
                raise RuntimeError("大型分块基线不允许单次自动修订；请禁用修订并按锁定结果评分")
            revised = self._call("repair", AgentTaskType.REQUIREMENT_ANALYSIS_REPAIR,
                                 OutputSchemaName.REQUIREMENT_BASELINE, prompts["repair-v1.md"][0],
                                 {"initial_baseline": _without_source_excerpts(initial),
                                  "findings": [f.model_dump(mode="json") for f in problems],
                                  "sources": _source_projection(_baseline_segment_ids(initial), documents)},
                                 (inputs, audits), attempt=2)
            validate_consolidation(revised, candidates, documents)
            revision_count = 1
            deterministic_results.append(deterministic_verify(revised, documents))
            revised_semantic = self._call("verify-revised", AgentTaskType.REQUIREMENT_VERIFICATION,
                                          OutputSchemaName.VERIFICATION_RESULT, prompts["semantic-verifier-v1.md"][0],
                                          {"baseline_sha256": digest(canonical_json(revised.model_dump(mode="json"))),
                                           "baseline": _without_source_excerpts(revised),
                                           "sources": _source_projection(_baseline_segment_ids(revised), documents)},
                                          (inputs, audits))
            validate_semantic_result(revised_semantic, revised)
            semantic_results.append(revised_semantic)
        run = RequirementAnalysisRun(
            prompt_versions={name: sha for name, (_, sha) in prompts.items()}, input_manifest=manifest, documents=documents,
            input_packages=inputs, audits=audits, responses=self.responses,
            candidates=candidates, initial_baseline=initial, deterministic_verifications=deterministic_results,
            semantic_verifications=semantic_results, baseline_fragments=fragments, reconciliation=reconciliation,
            revised_baseline=revised, revision_count=revision_count,
        )
        run.artifact_bundle()
        return run

    def resume_revision(
        self,
        documents: list[DocumentIR],
        manifest: InputManifest,
        candidates: list[RequirementCandidate],
        initial: RequirementBaseline,
        semantic: VerificationResult,
    ) -> RequirementAnalysisRun:
        """从已锁定的 repair 失败运行恢复，不重新执行提取、归并和初始语义核验。"""
        self.responses = []
        expected_sources = {(item.document_id, item.sha256) for item in manifest.files}
        actual_sources = {(item.source.document_id, item.source.sha256) for item in documents}
        if not documents or expected_sources != actual_sources:
            raise ValueError("Document IR 与输入清单不一致")
        validate_consolidation(initial, candidates, documents)
        initial_deterministic = deterministic_verify(initial, documents)
        validate_semantic_result(semantic, initial)
        problems = initial_deterministic.findings + [
            finding for finding in semantic.findings if finding.status != "supported"
        ]
        if not problems:
            raise ValueError("父运行没有需要修订的核验问题")

        repair_prompt, repair_hash = _read_prompt(self.prompt_root, "repair-v1.md")
        verifier_prompt, verifier_hash = _read_prompt(self.prompt_root, "semantic-verifier-v1.md")
        inputs, audits = [], []
        revised = self._call(
            "repair",
            AgentTaskType.REQUIREMENT_ANALYSIS_REPAIR,
            OutputSchemaName.REQUIREMENT_BASELINE,
            repair_prompt,
            {
                "initial_baseline": _without_source_excerpts(initial),
                "findings": [finding.model_dump(mode="json") for finding in problems],
                "sources": _source_projection(_baseline_segment_ids(initial), documents),
            },
            (inputs, audits),
            attempt=2,
        )
        try:
            validate_consolidation(revised, candidates, documents)
        except Exception as exc:
            raise AgentStepFailure("repair", inputs[-1], audits[-1], exc) from exc
        revised_deterministic = deterministic_verify(revised, documents)
        revised_semantic = self._call(
            "verify-revised",
            AgentTaskType.REQUIREMENT_VERIFICATION,
            OutputSchemaName.VERIFICATION_RESULT,
            verifier_prompt,
            {
                "baseline_sha256": digest(canonical_json(revised.model_dump(mode="json"))),
                "baseline": _without_source_excerpts(revised),
                "sources": _source_projection(_baseline_segment_ids(revised), documents),
            },
            (inputs, audits),
        )
        try:
            validate_semantic_result(revised_semantic, revised)
        except Exception as exc:
            raise AgentStepFailure("verify-revised", inputs[-1], audits[-1], exc) from exc

        run = RequirementAnalysisRun(
            prompt_versions={"repair-v1.md": repair_hash, "semantic-verifier-v1.md": verifier_hash},
            input_manifest=manifest,
            documents=documents,
            input_packages=inputs,
            audits=audits,
            responses=self.responses,
            candidates=candidates,
            initial_baseline=initial,
            deterministic_verifications=[initial_deterministic, revised_deterministic],
            semantic_verifications=[semantic, revised_semantic],
            revised_baseline=revised,
            revision_count=1,
        )
        run.artifact_bundle()
        return run
