from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from testing_platform.application.workflows.requirement_analysis import (
    AgentInputLimitExceeded, AgentStepFailure, CandidateSourceValidationError, RequirementAnalysisWorkflow,
    apply_reconciliation, assemble_baseline_fragments, baseline_subset, canonicalize_candidate_sources,
    deterministic_verify, normalize_baseline_fragment, persist_requirement_analysis_run,
    validate_candidate_sources, validate_consolidation, validate_reconciliation,
)
from testing_platform.domain.analysis import (
    RequirementBaseline, RequirementCandidate, RequirementReconciliation, VerificationResult,
)
from testing_platform.domain.documents import DocumentIR, ParseIssue, canonical_json, digest
from testing_platform.infrastructure.artifacts.local_artifact_store import LocalArtifactStore
from testing_platform.infrastructure.documents.ingestion import create_manifest, ingest
from testing_platform.infrastructure.hermes.skill_registry import SkillRegistry
from testing_platform.ports.agent_gateway import AgentResponse, AgentTaskType, AgentUsage
from scripts.run_requirement_prerun import BudgetExceeded, BudgetedGateway


class FakeGateway:
    def __init__(self, stage, payload): self.stage, self.payload, self.requests = stage, payload, []
    def run(self, request):
        self.requests.append(request)
        return AgentResponse(status="succeeded", structured_output=deepcopy(self.payload),
                             raw_response={"stage": self.stage, "payload": self.payload},
                             provider="fake", model="fake-model",
                             usage=AgentUsage(input_tokens=10, output_tokens=5))


class Factory:
    def __init__(self, payloads): self.payloads, self.instances, self.calls = payloads, [], []
    def __call__(self, stage):
        self.calls.append(stage)
        gateway = FakeGateway(stage, self.payloads[stage])
        self.instances.append(gateway)
        return gateway


class BudgetedFactory:
    def __init__(self, factory, usage, limits):
        self.factory, self.usage, self.limits = factory, usage, limits

    def __call__(self, stage):
        return BudgetedGateway(self.factory(stage), self.usage, self.limits)


def fixtures(tmp_path):
    path = tmp_path / "需求.md"
    path.write_text("# 订单\n\n数量范围为 1 至 999，包含边界。", encoding="utf-8")
    manifest = create_manifest([path], role="development")
    document = ingest(manifest.files[0])
    segment = next(s for s in document.segments if s.text.startswith("数量范围"))
    evidence = {"path": str(path.resolve()), "sha256": document.source.sha256, "segment_id": segment.id,
                "locator": segment.locator.model_dump(mode="json"), "excerpt": segment.text}
    requirement = {"id": "REQ-001", "target": "数量", "categories": ["boundary"],
                   "description": segment.text, "expected_behavior": "数量范围为 1 至 999，包含边界。",
                   "confidence": 1.0, "source_evidence": [evidence]}
    candidate = {"schema_version": "requirement-candidate/v1", "requirements": [requirement], "ambiguities": []}
    parsed = {"schema_version": "2.0", "source": {"path": str(path.resolve()), "sha256": document.source.sha256},
              "requirements": [requirement], "trace_index": {"REQ-001": [segment.id]}}
    baseline = {"schema_version": "requirement-baseline/v1", "parsed": parsed}
    baseline_hash = digest(canonical_json(RequirementBaseline.model_validate(baseline).model_dump(mode="json")))
    supported = {"schema_version": "verification-result/v1", "baseline_sha256": baseline_hash,
                 "method": "semantic", "findings": [{"requirement_id": "REQ-001", "status": "supported",
                                                        "code": "SEMANTIC_SUPPORTED", "message": "来源完整",
                                                        "segment_ids": [segment.id]}]}
    return manifest, document, candidate, baseline, supported


def workflow(factory, **kwargs):
    skill = SkillRegistry.from_file("configs/skills.yaml").resolve("requirement-analysis")
    return RequirementAnalysisWorkflow(factory, skill, **kwargs)


def test_independent_stages_generate_only_requirement_artifacts(tmp_path):
    manifest, document, candidate, baseline, supported = fixtures(tmp_path)
    factory = Factory({"extract-0": candidate, "consolidate": baseline, "verify": supported})
    run = workflow(factory).run([document], manifest)
    assert factory.calls == ["extract-0", "consolidate", "verify"]
    assert len({id(item) for item in factory.instances}) == 3
    assert run.revision_count == 0 and run.active_baseline == run.initial_baseline
    assert run.deterministic_verifications[0].findings == []
    bundle = run.artifact_bundle()
    assert "requirement-baseline-initial.json" in bundle
    assert not ({"plan", "cases", "test_cases", "test_items", "steps"} & set(bundle))
    assert all(a.model_id == "fake-model" and a.skill_version == "1.0.0" for a in run.audits)


def test_deterministic_codes_numeric_duplicate_missing_trace_and_failed_source(tmp_path):
    _, document, _, baseline_payload, _ = fixtures(tmp_path)
    parsed = baseline_payload["parsed"]
    parsed["requirements"][0]["expected_behavior"] = "数量范围为 1 至 1000。"
    duplicate = deepcopy(parsed["requirements"][0]); duplicate["id"] = "REQ-002"
    parsed["requirements"].append(duplicate)
    parsed["trace_index"] = {}
    baseline = RequirementBaseline.model_validate(baseline_payload)
    result = deterministic_verify(baseline, [document])
    codes = {f.code for f in result.findings}
    assert {"NUMERIC_FIDELITY_ERROR", "DUPLICATE_REQUIREMENT", "TRACE_INDEX_MISMATCH"} <= codes


def test_semantic_problem_triggers_at_most_one_audited_revision(tmp_path):
    manifest, document, candidate, baseline, supported = fixtures(tmp_path)
    problem = deepcopy(supported)
    problem["findings"][0].update(status="partially_supported", code="SEMANTIC_PARTIAL")
    factory = Factory({"extract-0": candidate, "consolidate": baseline, "verify": problem, "repair": baseline,
                       "verify-revised": supported})
    run = workflow(factory).run([document], manifest, allow_revision=True)
    assert factory.calls == ["extract-0", "consolidate", "verify", "repair", "verify-revised"]
    assert run.revision_count == 1 and run.revised_baseline is not None
    assert len(run.initial_baseline.model_dump_json()) > 0
    assert run.audits[-2].attempt == 2
    assert len(run.semantic_verifications) == 2


def test_revision_resume_only_calls_repair_and_revised_verifier(tmp_path):
    manifest, document, candidate, baseline, supported = fixtures(tmp_path)
    problem = deepcopy(supported)
    problem["findings"][0].update(status="partially_supported", code="SEMANTIC_PARTIAL")
    factory = Factory({"repair": baseline, "verify-revised": supported})

    run = workflow(factory).resume_revision(
        [document],
        manifest,
        [RequirementCandidate.model_validate(candidate)],
        RequirementBaseline.model_validate(baseline),
        VerificationResult.model_validate(problem),
    )

    assert factory.calls == ["repair", "verify-revised"]
    assert run.revision_count == 1 and run.revised_baseline is not None
    assert len(run.deterministic_verifications) == 2
    assert len(run.semantic_verifications) == 2
    repair_input = json.loads(factory.instances[0].requests[0].user_input)
    assert repair_input["findings"][0]["code"] == "SEMANTIC_PARTIAL"


def test_forbidden_case_output_is_rejected(tmp_path):
    manifest, document, candidate, baseline, supported = fixtures(tmp_path)
    candidate["cases"] = []
    factory = Factory({"extract-0": candidate, "consolidate": baseline, "verify": supported})
    with pytest.raises(AgentStepFailure, match="禁止字段"):
        workflow(factory).run([document], manifest)


def test_extractor_contract_splits_rules_and_keeps_insufficient_source_as_ambiguity(tmp_path):
    _, _, candidate, _, _ = fixtures(tmp_path)
    second = deepcopy(candidate["requirements"][0])
    second.update(id="REQ-002", target="保存", categories=["functional"],
                  description="应保存订单", expected_behavior="订单被保存")
    split = RequirementCandidate.model_validate({**candidate, "requirements": [candidate["requirements"][0], second]})
    assert len(split.requirements) == 2
    ambiguity_only = RequirementCandidate.model_validate({
        "schema_version": "requirement-candidate/v1", "requirements": [],
        "ambiguities": [{"id": "A1", "description": "响应应及时，但没有时间标准", "impact": "无法判断性能是否通过"}],
    })
    assert not ambiguity_only.requirements and ambiguity_only.ambiguities
    bad = deepcopy(candidate); bad["requirements"][0]["source_evidence"] = []
    with pytest.raises(ValueError):
        RequirementCandidate.model_validate(bad)


def test_consolidation_preserves_multi_source_synonym_and_numeric_conflict(tmp_path):
    files = []
    for name, text in (("a.md", "客户名称必填。超时为 5 秒。"), ("b.md", "客户名不得为空。超时为 8 秒。")):
        path = tmp_path / name; path.write_text(text, encoding="utf-8"); files.append(path)
    manifest = create_manifest(files, role="development")
    documents = [ingest(item) for item in manifest.files]
    segments = [next(s for s in doc.segments if s.text) for doc in documents]

    def evidence(index):
        return {"path": documents[index].source.path, "sha256": documents[index].source.sha256,
                "segment_id": segments[index].id, "locator": segments[index].locator.model_dump(),
                "excerpt": segments[index].text}

    def requirement(identifier, target, description, expected, source_index, category="functional"):
        return {"id": identifier, "target": target, "categories": [category], "description": description,
                "expected_behavior": expected, "confidence": 1, "source_evidence": [evidence(source_index)]}

    candidates = [
        RequirementCandidate.model_validate({"schema_version": "requirement-candidate/v1", "requirements": [
            requirement("A1", "客户名称", "客户名称必填。", "客户名称非空", 0),
            requirement("A2", "超时", "超时为 5 秒。", "超时为 5 秒", 0, "performance")]}),
        RequirementCandidate.model_validate({"schema_version": "requirement-candidate/v1", "requirements": [
            requirement("B1", "客户名", "客户名不得为空。", "客户名非空", 1),
            requirement("B2", "超时", "超时为 8 秒。", "超时为 8 秒", 1, "performance")]})]
    merged = requirement("R1", "客户名称", "客户名称必填。", "客户名称非空", 0)
    merged["source_evidence"].append(evidence(1))
    five = requirement("R2", "超时", "超时为 5 秒。", "超时为 5 秒", 0, "performance")
    eight = requirement("R3", "超时", "超时为 8 秒。", "超时为 8 秒", 1, "performance")
    baseline_payload = {
        "schema_version": "requirement-baseline/v1",
        "parsed": {"schema_version": "2.0", "source": {"path": manifest.files[0].path, "sha256": manifest.files[0].sha256,
                                                                    "name": manifest.files[0].name, "media_type": "text/markdown"},
                   "additional_sources": [{"path": manifest.files[1].path, "sha256": manifest.files[1].sha256,
                                            "name": manifest.files[1].name, "media_type": "text/markdown"}],
                   "requirements": [merged, five, eight],
                   "ambiguities": [{"id": "TERM-1", "description": "客户名称与客户名是否同义需要确认", "impact": "影响归并",
                                     "requirement_ids": ["R1"], "source_evidence": [evidence(0), evidence(1)]}],
                   "conflicts": [{"id": "CONFLICT-1", "description": "超时阈值冲突", "impact": "无法确定验收值",
                                  "requirement_ids": ["R2", "R3"], "source_evidence": [evidence(0), evidence(1)]}],
                   "trace_index": {"R1": [segments[0].id, segments[1].id], "R2": [segments[0].id], "R3": [segments[1].id]}}}
    baseline = RequirementBaseline.model_validate(baseline_payload)
    validate_consolidation(baseline, candidates, documents)
    assert len(baseline.parsed.requirements[0].source_evidence) == 2
    bad = deepcopy(baseline_payload); bad["parsed"]["conflicts"][0]["source_evidence"] = [evidence(0)]
    with pytest.raises(ValueError, match="双方来源"):
        validate_consolidation(RequirementBaseline.model_validate(bad), candidates, documents)


def test_fragment_normalization_assembly_and_reconciliation_are_deterministic(tmp_path):
    _, _, _, baseline_payload, _ = fixtures(tmp_path)
    first = normalize_baseline_fragment(RequirementBaseline.model_validate(deepcopy(baseline_payload)), 0)
    second = normalize_baseline_fragment(RequirementBaseline.model_validate(deepcopy(baseline_payload)), 1)
    assembled = assemble_baseline_fragments([first, second])
    reconciliation = RequirementReconciliation.model_validate({
        "schema_version": "requirement-reconciliation/v1",
        "merges": [{"requirement_ids": ["REQ-C00-001", "REQ-C01-001"],
                    "retained_id": "REQ-C00-001", "rationale": "同义重复"}],
        "conflicts": [],
        "ambiguities": [],
    })

    final = apply_reconciliation(assembled, reconciliation)

    assert [item.id for item in assembled.parsed.requirements] == ["REQ-C00-001", "REQ-C01-001"]
    assert [item.id for item in final.parsed.requirements] == ["REQ-C00-001"]
    assert final.parsed.trace_index == {
        "REQ-C00-001": [first.parsed.requirements[0].source_evidence[0].segment_id]
    }


def test_reconciliation_rejects_unknown_reused_and_numeric_conflict_ids(tmp_path):
    _, _, _, baseline_payload, _ = fixtures(tmp_path)
    first = normalize_baseline_fragment(RequirementBaseline.model_validate(deepcopy(baseline_payload)), 0)
    same = normalize_baseline_fragment(RequirementBaseline.model_validate(deepcopy(baseline_payload)), 1)
    changed = deepcopy(baseline_payload)
    changed["parsed"]["requirements"][0]["expected_behavior"] = "数量范围为 1 至 1000。"
    second = normalize_baseline_fragment(RequirementBaseline.model_validate(changed), 1)
    assembled = assemble_baseline_fragments([first, second])
    same_assembled = assemble_baseline_fragments([first, same])

    def reconciliation(merges):
        return RequirementReconciliation.model_validate({
            "schema_version": "requirement-reconciliation/v1", "merges": merges,
            "conflicts": [], "ambiguities": [],
        })

    with pytest.raises(ValueError, match="未知需求"):
        validate_reconciliation(reconciliation([{
            "requirement_ids": ["REQ-C00-001", "UNKNOWN"], "retained_id": "REQ-C00-001", "rationale": "x",
        }]), assembled)
    with pytest.raises(ValueError, match="多个跨块合并"):
        validate_reconciliation(reconciliation([
            {"requirement_ids": ["REQ-C00-001", "REQ-C01-001"], "retained_id": "REQ-C00-001", "rationale": "x"},
            {"requirement_ids": ["REQ-C00-001", "REQ-C01-001"], "retained_id": "REQ-C01-001", "rationale": "x"},
        ]), same_assembled)
    with pytest.raises(ValueError, match="数值、单位或边界"):
        validate_reconciliation(reconciliation([{
            "requirement_ids": ["REQ-C00-001", "REQ-C01-001"],
            "retained_id": "REQ-C00-001", "rationale": "错误地视为同义",
        }]), assembled)

    conflict = RequirementReconciliation.model_validate({
        "schema_version": "requirement-reconciliation/v1", "merges": [],
        "conflicts": [{"requirement_ids": ["REQ-C00-001", "REQ-C01-001"],
                       "description": "数值上限冲突", "impact": "无法确定验收值"}],
        "ambiguities": [],
    })
    preserved = apply_reconciliation(assembled, conflict)
    assert len(preserved.parsed.requirements) == 2
    assert preserved.parsed.conflicts[-1].requirement_ids == ["REQ-C00-001", "REQ-C01-001"]
    assert preserved.parsed.conflicts[-1].source_evidence


def test_baseline_subset_keeps_only_requested_requirements(tmp_path):
    _, _, _, baseline_payload, _ = fixtures(tmp_path)
    first = normalize_baseline_fragment(RequirementBaseline.model_validate(deepcopy(baseline_payload)), 0)
    second = normalize_baseline_fragment(RequirementBaseline.model_validate(deepcopy(baseline_payload)), 1)
    assembled = assemble_baseline_fragments([first, second])

    subset = baseline_subset(assembled, ["REQ-C01-001"])

    assert [item.id for item in subset.parsed.requirements] == ["REQ-C01-001"]
    assert set(subset.parsed.trace_index) == {"REQ-C01-001"}


def test_chunked_consolidation_and_verification_never_return_full_baseline_in_one_response(tmp_path):
    _, document, candidate_payload, baseline_payload, _ = fixtures(tmp_path)
    candidates = [RequirementCandidate.model_validate(deepcopy(candidate_payload)) for _ in range(3)]
    fragment = deepcopy(baseline_payload)
    empty_reconciliation = {
        "schema_version": "requirement-reconciliation/v1", "merges": [], "conflicts": [], "ambiguities": [],
    }
    factory = Factory({
        "consolidate-0": fragment,
        "consolidate-1": fragment,
        "reconcile": empty_reconciliation,
    })
    instance = workflow(factory, max_consolidation_candidates=2, max_verification_requirements=1)
    prompts = {
        name: (Path("prompts/requirement-analysis", name).read_text(encoding="utf-8"), "hash")
        for name in ("consolidator-v1.md", "consolidator-fragment-v1.md", "reconciliation-v1.md")
    }
    records = ([], [])

    initial, fragments, reconciliation = instance._consolidate(candidates, [document], prompts, records)

    expected_hash = digest(canonical_json(initial.model_dump(mode="json")))
    for index, requirement in enumerate(initial.parsed.requirements):
        factory.payloads[f"verify-{index}"] = {
            "schema_version": "verification-result/v1", "baseline_sha256": expected_hash,
            "method": "semantic", "findings": [{
                "requirement_id": requirement.id, "status": "supported",
                "code": "SEMANTIC_SUPPORTED", "message": "来源支持", "segment_ids": [],
            }],
        }
    semantic = instance._semantic_verify(
        initial, [document], Path("prompts/requirement-analysis/semantic-verifier-v1.md").read_text(encoding="utf-8"),
        records,
    )

    assert factory.calls == ["consolidate-0", "consolidate-1", "reconcile", "verify-0", "verify-1"]
    assert len(fragments) == 2 and reconciliation is not None
    assert [item.requirement_id for item in semantic.findings] == ["REQ-C00-001", "REQ-C01-001"]
    assert all(len(json.loads(gateway.requests[0].user_input).get("baseline", {}).get("parsed", {}).get("requirements", [])) <= 1
               for gateway in factory.instances[-2:])


def test_failed_segment_is_indeterminate_and_bundle_can_be_persisted(tmp_path):
    manifest, document, candidate, baseline_payload, supported = fixtures(tmp_path)
    raw = document.model_dump(mode="json")
    raw["segments"][-1]["status"] = "unknown"
    raw["issues"] = [{"code": "UNKNOWN_OBJECT", "message": "无法解释", "segment_id": raw["segments"][-1]["id"]}]
    affected = DocumentIR.model_validate(raw)
    result = deterministic_verify(RequirementBaseline.model_validate(baseline_payload), [affected])
    assert any(f.code == "FAILED_SEGMENT_REFERENCE" and f.status == "indeterminate" for f in result.findings)
    factory = Factory({"extract-0": candidate, "consolidate": baseline_payload, "verify": supported})
    run = workflow(factory).run([document], manifest)
    store = LocalArtifactStore(tmp_path / "artifacts")
    references = persist_requirement_analysis_run(run, store, uuid4())
    assert references and all(store.resolve(item).is_file() and item.sha256 for item in references)
    assert {item.name for item in references} >= {"input-manifest.json", "document-ir.json", "trace-index.json"}


def test_extraction_windows_exclude_empty_and_unknown_segments_but_keep_document_ir(tmp_path):
    _, document, _, _, _ = fixtures(tmp_path)
    raw = document.model_dump(mode="json")
    raw["segments"][-1]["status"] = "unknown"
    raw["issues"] = [{"code": "UNKNOWN_OBJECT", "message": "无法解释",
                      "segment_id": raw["segments"][-1]["id"]}]
    affected = DocumentIR.model_validate(raw)
    windows = workflow(Factory({}))._windows([affected])
    window_ids = {item["segment"]["id"] for window in windows for item in window["segments"]}
    assert affected.segments[-1].id not in window_ids
    assert affected.segments[-1].id in {item.id for item in affected.segments}
    assert affected.issues[0].segment_id == affected.segments[-1].id


def test_workflow_rejects_document_without_analyzable_text(tmp_path):
    manifest, document, _, _, _ = fixtures(tmp_path)
    raw = document.model_dump(mode="json")
    for segment in raw["segments"]:
        segment["status"] = "empty"
        segment["text"] = ""
    with pytest.raises(ValueError, match="已解析文本片段"):
        workflow(Factory({})).run([DocumentIR.model_validate(raw)], manifest)


def test_semantic_verifier_receives_hash_and_must_cover_every_requirement(tmp_path):
    manifest, document, candidate, baseline, supported = fixtures(tmp_path)
    factory = Factory({"extract-0": candidate, "consolidate": baseline, "verify": supported})
    run = workflow(factory).run([document], manifest)
    import json
    package = json.loads(factory.instances[-1].requests[0].user_input)
    assert package["baseline_sha256"] == supported["baseline_sha256"]
    assert run.responses[-1]["raw_response"] and "temperature" not in run.audits[-1].parameters
    supported["findings"] = []
    with pytest.raises(AgentStepFailure) as failure:
        workflow(factory).run([document], manifest)
    assert failure.value.stage == "verify"
    assert "覆盖每条需求" in str(failure.value.cause)


def test_later_stages_receive_only_deduplicated_cited_source_segments(tmp_path):
    manifest, document, candidate, baseline, supported = fixtures(tmp_path)
    duplicate = deepcopy(candidate["requirements"][0])
    duplicate["id"] = "REQ-002"
    candidate["requirements"].append(duplicate)
    factory = Factory({"extract-0": candidate, "consolidate": baseline, "verify": supported})

    workflow(factory).run([document], manifest)

    consolidation = json.loads(factory.instances[1].requests[0].user_input)
    semantic = json.loads(factory.instances[2].requests[0].user_input)
    assert "documents" not in consolidation and "documents" not in semantic
    assert len(consolidation["sources"][0]["segments"]) == 1
    assert len(semantic["sources"][0]["segments"]) == 1
    assert consolidation["sources"][0]["segments"][0]["text"] == document.segments[-1].text
    assert "excerpt" not in consolidation["candidates"][0]["requirements"][0]["source_evidence"][0]
    assert "excerpt" not in semantic["baseline"]["parsed"]["requirements"][0]["source_evidence"][0]


def test_oversized_agent_input_fails_before_gateway_and_budget_accounting(tmp_path):
    manifest, document, candidate, baseline, supported = fixtures(tmp_path)
    factory = Factory({"extract-0": candidate, "consolidate": baseline, "verify": supported})
    usage = {"agent_calls": 0, "input_tokens": 0, "output_tokens": 0, "calls": [], "violations": []}
    limits = {"max_agent_calls": 20, "max_input_tokens": 1000, "max_output_tokens": 1000}
    events = {}
    instance = workflow(BudgetedFactory(factory, usage, limits), max_agent_input_chars=1)
    instance.event_sink = lambda name, payload: events.update({name: payload})

    with pytest.raises(AgentInputLimitExceeded) as failure:
        instance.run([document], manifest)

    assert failure.value.stage == "extract-0"
    assert failure.value.actual_chars > failure.value.limit_chars == 1
    assert factory.calls == []
    assert usage["agent_calls"] == usage["input_tokens"] == usage["output_tokens"] == 0
    assert usage["calls"] == []
    assert events["extract-0-input-rejected"] == {
        "stage": "extract-0", "actual_chars": failure.value.actual_chars, "limit_chars": 1,
    }


def test_invalid_reference_metadata_is_not_supported(tmp_path):
    _, document, _, baseline, _ = fixtures(tmp_path)
    baseline["parsed"]["requirements"][0]["source_evidence"][0]["sha256"] = "f" * 64
    result = deterministic_verify(RequirementBaseline.model_validate(baseline), [document])
    assert any(item.code == "SOURCE_REFERENCE_MISMATCH" for item in result.findings)


def test_extraction_input_includes_source_path_and_rejects_invented_candidate_path(tmp_path):
    manifest, document, candidate, baseline, supported = fixtures(tmp_path)
    factory = Factory({"extract-0": candidate, "consolidate": baseline, "verify": supported})
    workflow(factory).run([document], manifest)
    import json
    first_input = json.loads(factory.instances[0].requests[0].user_input)
    assert first_input["segments"][0]["document"]["path"] == document.source.path
    invented = RequirementCandidate.model_validate(candidate).model_copy(deep=True)
    invented.requirements[0].source_evidence[0].path = "doc-invented"
    with pytest.raises(ValueError, match="原值"):
        validate_candidate_sources(invented, [document])


def test_candidate_source_metadata_is_canonicalized_from_valid_segment_id(tmp_path):
    _, document, candidate, _, _ = fixtures(tmp_path)
    draft = RequirementCandidate.model_validate(candidate).model_copy(deep=True)
    ref = draft.requirements[0].source_evidence[0]
    ref.path = "模型误抄路径"
    ref.sha256 = "f" * 64
    ref.locator.line_start = 999
    normalized, changes = canonicalize_candidate_sources(draft, [document])
    validate_candidate_sources(normalized, [document])
    assert changes == [{"owner_type": "requirement", "owner_id": "REQ-001",
                        "segment_id": ref.segment_id, "fields": ["path", "sha256", "locator"]}]
    assert normalized.requirements[0].source_evidence[0].path == document.source.path


def test_candidate_source_canonicalization_does_not_hide_rewritten_excerpt(tmp_path):
    _, document, candidate, _, _ = fixtures(tmp_path)
    draft = RequirementCandidate.model_validate(candidate).model_copy(deep=True)
    draft.requirements[0].source_evidence[0].excerpt = "数量范围改写为 1 至 999。"
    with pytest.raises(CandidateSourceValidationError, match="连续原文") as failure:
        canonicalize_candidate_sources(draft, [document])
    assert failure.value.as_payload() == {
        "code": "SOURCE_EXCERPT_MISMATCH",
        "owner_type": "requirement",
        "owner_id": "REQ-001",
        "segment_id": draft.requirements[0].source_evidence[0].segment_id,
        "message": "REQ-001: 候选摘录不是输入片段的连续原文",
    }


def test_candidate_source_canonicalization_rejects_unknown_segment(tmp_path):
    _, document, candidate, _, _ = fixtures(tmp_path)
    draft = RequirementCandidate.model_validate(candidate)
    draft.requirements[0].source_evidence[0].segment_id = "seg-invented"
    with pytest.raises(ValueError, match="不存在的片段"):
        canonicalize_candidate_sources(draft, [document])


def test_fixed_response_reproduces_single_unknown_segment_failure(tmp_path):
    _, document, candidate, _, _ = fixtures(tmp_path)
    draft = RequirementCandidate.model_validate(candidate).model_copy(deep=True)
    draft.requirements[0].source_evidence[0].segment_id = "seg-fixed-invalid"

    failures = []
    for _ in range(2):
        with pytest.raises(CandidateSourceValidationError) as failure:
            canonicalize_candidate_sources(draft, [document])
        failures.append(failure.value.as_payload())

    assert failures[0] == failures[1] == {
        "code": "SOURCE_SEGMENT_MISSING",
        "owner_type": "requirement",
        "owner_id": "REQ-001",
        "segment_id": "seg-fixed-invalid",
        "message": "REQ-001: 候选引用了不存在的片段",
    }


def test_workflow_repairs_unknown_source_once_and_audits_both_responses(tmp_path):
    manifest, document, candidate, baseline, supported = fixtures(tmp_path)
    original = deepcopy(candidate)
    original["requirements"][0]["source_evidence"][0]["segment_id"] = "seg-fixed-invalid"
    repaired = deepcopy(original)
    valid_segment = candidate["requirements"][0]["source_evidence"][0]["segment_id"]
    repaired["requirements"][0]["source_evidence"][0]["segment_id"] = valid_segment
    factory = Factory({
        "extract-0": original,
        "extract-0-source-repair": repaired,
        "consolidate": baseline,
        "verify": supported,
    })

    run = workflow(factory).run([document], manifest)

    assert factory.calls == ["extract-0", "extract-0-source-repair", "consolidate", "verify"]
    repair_request = factory.instances[1].requests[0]
    repair_input = json.loads(repair_request.user_input)
    assert repair_request.task_type == AgentTaskType.REQUIREMENT_SOURCE_REPAIR
    assert repair_request.attempt == 2
    assert set(repair_input) == {"original_candidate", "validation_error", "valid_segments"}
    assert repair_input["original_candidate"] == RequirementCandidate.model_validate(original).model_dump(mode="json")
    assert repair_input["validation_error"]["segment_id"] == "seg-fixed-invalid"
    assert repair_input["valid_segments"] == [
        {"segment_id": item["segment"]["id"], "text": item["segment"]["text"]}
        for item in workflow(Factory({}))._windows([document])[0]["segments"]
    ]
    assert [item["stage"] for item in run.responses[:2]] == ["extract-0", "extract-0-source-repair"]
    assert run.responses[0]["raw_response"]["payload"] == original
    assert run.responses[1]["raw_response"]["payload"] == repaired
    assert run.audits[1].task_type == AgentTaskType.REQUIREMENT_SOURCE_REPAIR
    assert run.candidates[0].requirements[0].source_evidence[0].segment_id == valid_segment
    assert "source-repair-v1.md" in run.prompt_versions


def test_source_repair_call_is_included_in_existing_budget_accounting(tmp_path):
    manifest, document, candidate, baseline, supported = fixtures(tmp_path)
    original = deepcopy(candidate)
    original["requirements"][0]["source_evidence"][0]["segment_id"] = "seg-fixed-invalid"
    repaired = deepcopy(original)
    repaired["requirements"][0]["source_evidence"][0]["segment_id"] = candidate["requirements"][0]["source_evidence"][0]["segment_id"]
    factory = Factory({
        "extract-0": original,
        "extract-0-source-repair": repaired,
        "consolidate": baseline,
        "verify": supported,
    })
    usage = {"agent_calls": 0, "input_tokens": 0, "output_tokens": 0,
             "token_usage_complete": True, "violations": [], "calls": []}
    limits = {"max_agent_calls": 10, "max_input_tokens": 1000, "max_output_tokens": 1000}

    workflow(BudgetedFactory(factory, usage, limits)).run([document], manifest)

    assert usage["agent_calls"] == 4
    assert usage["input_tokens"] == 40 and usage["output_tokens"] == 20
    assert [call["stage"] for call in usage["calls"]] == [
        "extract-0", "extract-0-source-repair", "consolidate", "verify",
    ]


def test_workflow_repairs_excerpt_mismatch_once_and_preserves_original_response(tmp_path):
    manifest, document, candidate, baseline, supported = fixtures(tmp_path)
    original = deepcopy(candidate)
    original["requirements"][0]["source_evidence"][0]["excerpt"] = "数量范围改写为 1 至 999。"
    repaired = deepcopy(candidate)
    factory = Factory({
        "extract-0": original,
        "extract-0-source-repair": repaired,
        "consolidate": baseline,
        "verify": supported,
    })
    events = {}
    instance = workflow(factory)
    instance.event_sink = lambda name, payload: events.update({name: payload})

    run = instance.run([document], manifest)

    assert factory.calls == ["extract-0", "extract-0-source-repair", "consolidate", "verify"]
    assert events["extract-0-source-validation-error"]["code"] == "SOURCE_EXCERPT_MISMATCH"
    repair_input = json.loads(factory.instances[1].requests[0].user_input)
    assert repair_input["validation_error"]["code"] == "SOURCE_EXCERPT_MISMATCH"
    assert run.responses[0]["raw_response"]["payload"] == original
    assert run.responses[1]["raw_response"]["payload"] == repaired
    assert run.candidates[0].requirements[0].source_evidence[0].excerpt == \
        candidate["requirements"][0]["source_evidence"][0]["excerpt"]


def test_excerpt_source_repair_still_invalid_fails_without_second_repair(tmp_path):
    manifest, document, candidate, _, _ = fixtures(tmp_path)
    original = deepcopy(candidate)
    original["requirements"][0]["source_evidence"][0]["excerpt"] = "第一次错误摘录"
    repaired = deepcopy(candidate)
    repaired["requirements"][0]["source_evidence"][0]["excerpt"] = "第二次错误摘录"
    factory = Factory({"extract-0": original, "extract-0-source-repair": repaired})

    with pytest.raises(AgentStepFailure) as failure:
        workflow(factory).run([document], manifest)

    assert failure.value.stage == "extract-0-source-repair"
    assert isinstance(failure.value.cause, CandidateSourceValidationError)
    assert failure.value.cause.code == "SOURCE_EXCERPT_MISMATCH"
    assert factory.calls == ["extract-0", "extract-0-source-repair"]


def test_excerpt_source_repair_obeys_existing_call_budget(tmp_path):
    manifest, document, candidate, _, _ = fixtures(tmp_path)
    original = deepcopy(candidate)
    original["requirements"][0]["source_evidence"][0]["excerpt"] = "错误摘录"
    factory = Factory({"extract-0": original, "extract-0-source-repair": candidate})
    usage = {"agent_calls": 0, "input_tokens": 0, "output_tokens": 0,
             "token_usage_complete": True, "violations": [], "calls": []}
    limits = {"max_agent_calls": 1, "max_input_tokens": 1000, "max_output_tokens": 1000}

    with pytest.raises(BudgetExceeded, match="调用次数"):
        workflow(BudgetedFactory(factory, usage, limits)).run([document], manifest)

    assert factory.calls == ["extract-0", "extract-0-source-repair"]
    assert factory.instances[1].requests == []
    assert usage["agent_calls"] == 1


def test_source_repair_is_blocked_before_upstream_call_when_call_budget_is_exhausted(tmp_path):
    manifest, document, candidate, _, _ = fixtures(tmp_path)
    original = deepcopy(candidate)
    original["requirements"][0]["source_evidence"][0]["segment_id"] = "seg-fixed-invalid"
    factory = Factory({"extract-0": original, "extract-0-source-repair": candidate})
    usage = {"agent_calls": 0, "input_tokens": 0, "output_tokens": 0,
             "token_usage_complete": True, "violations": [], "calls": []}
    limits = {"max_agent_calls": 1, "max_input_tokens": 1000, "max_output_tokens": 1000}

    with pytest.raises(BudgetExceeded, match="调用次数"):
        workflow(BudgetedFactory(factory, usage, limits)).run([document], manifest)

    assert factory.calls == ["extract-0", "extract-0-source-repair"]
    assert factory.instances[0].requests
    assert factory.instances[1].requests == []
    assert usage["agent_calls"] == 1
    assert [call["stage"] for call in usage["calls"]] == ["extract-0"]


def test_candidate_source_must_belong_to_current_window(tmp_path):
    _, document, candidate, _, _ = fixtures(tmp_path)
    draft = RequirementCandidate.model_validate(candidate)
    paragraph_id = draft.requirements[0].source_evidence[0].segment_id
    other_segment_id = next(segment.id for segment in document.segments if segment.id != paragraph_id)
    draft.requirements[0].source_evidence[0].segment_id = other_segment_id

    with pytest.raises(CandidateSourceValidationError) as failure:
        canonicalize_candidate_sources(draft, [document], allowed_segment_ids={paragraph_id})

    assert failure.value.code == "SOURCE_SEGMENT_OUTSIDE_WINDOW"
    assert failure.value.segment_id == other_segment_id


def test_source_repair_cannot_move_evidence_outside_current_window(tmp_path):
    manifest, document, candidate, _, _ = fixtures(tmp_path)
    original = deepcopy(candidate)
    original["requirements"][0]["source_evidence"][0]["segment_id"] = "seg-fixed-invalid"
    repaired = deepcopy(candidate)
    factory = Factory({"extract-0": original, "extract-0-source-repair": repaired})

    with pytest.raises(AgentStepFailure) as failure:
        workflow(factory, max_window_segments=1).run([document], manifest)

    assert failure.value.stage == "extract-0-source-repair"
    assert isinstance(failure.value.cause, CandidateSourceValidationError)
    assert failure.value.cause.code == "SOURCE_SEGMENT_OUTSIDE_WINDOW"
    assert factory.calls == ["extract-0", "extract-0-source-repair"]


def test_source_repair_cannot_change_candidate_semantics(tmp_path):
    manifest, document, candidate, _, _ = fixtures(tmp_path)
    original = deepcopy(candidate)
    original["requirements"][0]["source_evidence"][0]["segment_id"] = "seg-fixed-invalid"
    repaired = deepcopy(candidate)
    repaired["requirements"][0]["description"] = "被修复调用改写的需求"
    factory = Factory({"extract-0": original, "extract-0-source-repair": repaired})

    with pytest.raises(AgentStepFailure) as failure:
        workflow(factory).run([document], manifest)

    assert failure.value.stage == "extract-0-source-repair"
    assert "不得修改、删除或重排候选内容" in str(failure.value.cause)
    assert factory.calls == ["extract-0", "extract-0-source-repair"]


def test_source_repair_still_invalid_fails_without_second_repair(tmp_path):
    manifest, document, candidate, _, _ = fixtures(tmp_path)
    original = deepcopy(candidate)
    original["requirements"][0]["source_evidence"][0]["segment_id"] = "seg-first-invalid"
    repaired = deepcopy(original)
    repaired["requirements"][0]["source_evidence"][0]["segment_id"] = "seg-second-invalid"
    factory = Factory({"extract-0": original, "extract-0-source-repair": repaired})

    with pytest.raises(AgentStepFailure) as failure:
        workflow(factory).run([document], manifest)

    assert failure.value.stage == "extract-0-source-repair"
    assert "不存在的片段" in str(failure.value.cause)
    assert factory.calls == ["extract-0", "extract-0-source-repair"]


def test_workflow_preserves_raw_source_error_and_records_normalization(tmp_path):
    manifest, document, candidate, baseline, supported = fixtures(tmp_path)
    candidate = deepcopy(candidate)
    wrong_hash = "f" * 64
    candidate["requirements"][0]["source_evidence"][0]["sha256"] = wrong_hash
    factory = Factory({"extract-0": candidate, "consolidate": baseline, "verify": supported})
    events = {}
    instance = workflow(factory)
    instance.event_sink = lambda name, payload: events.update({name: payload})
    run = instance.run([document], manifest)
    assert events["extract-0-response"]["raw_response"]["payload"]["requirements"][0]["source_evidence"][0]["sha256"] == wrong_hash
    assert run.responses[0]["raw_response"]["payload"]["requirements"][0]["source_evidence"][0]["sha256"] == wrong_hash
    assert events["extract-0-source-normalization"]["changes"] == [
        {"owner_type": "requirement", "owner_id": "REQ-001",
         "segment_id": candidate["requirements"][0]["source_evidence"][0]["segment_id"], "fields": ["sha256"]}
    ]
    assert run.candidates[0].requirements[0].source_evidence[0].sha256 == document.source.sha256
    import json
    consolidation_input = json.loads(factory.instances[1].requests[0].user_input)
    assert consolidation_input["candidates"][0]["requirements"][0]["source_evidence"][0]["sha256"] == document.source.sha256
    assert run.deterministic_verifications[0].findings == []


def test_invalid_response_is_preserved_before_validation_failure(tmp_path):
    manifest, document, _, _, _ = fixtures(tmp_path)
    factory = Factory({"extract-0": {"invalid": True}})
    events = {}
    instance = workflow(factory)
    instance.event_sink = lambda name, payload: events.update({name: payload})
    with pytest.raises(AgentStepFailure):
        instance.run([document], manifest)
    assert events["extract-0-response"]["raw_response"]["payload"] == {"invalid": True}
    assert events["extract-0-input"]["request_sha256"]


def test_consolidator_prompt_requires_complete_source_metadata():
    prompt = Path("prompts/requirement-analysis/consolidator-v1.md").read_text(encoding="utf-8")
    assert all(field in prompt for field in ("`path`", "`sha256`", "`segment_id`", "`locator`"))
    assert "不得为了压缩输出省略字段" in prompt
    assert all(field in prompt for field in ("`target`", "`categories`", "`description`", "`expected_behavior`", "`confidence`"))
    assert "不得因 JSON Schema 中存在兼容默认值而省略" in prompt
    assert "返回前检查 JSON 语法完整" in prompt


def test_fragment_consolidator_prompt_requires_parsed_requirements_v2():
    prompt = Path("prompts/requirement-analysis/consolidator-fragment-v1.md").read_text(encoding="utf-8")
    assert "`parsed.schema_version` 必须明确为 `2.0`" in prompt
    assert "不得使用兼容旧消费者的 `1.0`" in prompt


def test_extractor_prompt_requires_exact_optional_excerpt():
    prompt = Path("prompts/requirement-analysis/section-extractor-v1.md").read_text(encoding="utf-8")
    assert "`excerpt` 是可选字段" in prompt
    assert "连续原文" in prompt and "不得删改括号、句号" in prompt


def test_source_repair_prompt_limits_changes_and_requires_exact_excerpt():
    prompt = Path("prompts/requirement-analysis/source-repair-v1.md").read_text(encoding="utf-8")
    assert "仅可修改" in prompt and "`source_evidence`" in prompt
    assert "不得修改、删除、新增或重排任何候选" in prompt
    assert "连续原文" in prompt
    assert "无法从当前窗口确定正确来源" in prompt


def test_repair_prompt_preserves_v2_fields_and_source_metadata():
    prompt = Path("prompts/requirement-analysis/repair-v1.md").read_text(encoding="utf-8")
    assert all(field in prompt for field in (
        "`target`", "`categories`", "`description`", "`expected_behavior`", "`confidence`",
        "`path`", "`sha256`", "`segment_id`", "`locator`",
    ))
    assert "不得为压缩输出而省略" in prompt
    assert "v2 必填字段完整" in prompt


