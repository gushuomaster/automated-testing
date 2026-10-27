"""只读重放 v4 候选，验证 v5 分块拓扑；不调用模型、不计算正式成绩。"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from run_requirement_prerun import BudgetedGateway
from testing_platform.application.workflows.requirement_analysis import (
    RequirementAnalysisWorkflow, canonicalize_candidate_sources,
)
from testing_platform.domain.analysis import RequirementBaseline, RequirementCandidate
from testing_platform.domain.documents import DocumentIR, canonical_json, digest
from testing_platform.domain.requirements import ParsedRequirements, RequirementItem
from testing_platform.infrastructure.hermes.skill_registry import SkillRegistry
from testing_platform.ports.agent_gateway import AgentResponse, AgentUsage


RUN = Path("artifacts/requirement-analysis/preruns/formal/05020ec8-d75d-4702-be31-d5d61886026f")


def load_candidates(documents: list[DocumentIR]) -> list[RequirementCandidate]:
    candidates = []
    for index in range(14):
        response = json.loads((RUN / "stages" / f"extract-{index}-response.json").read_text(encoding="utf-8"))
        package = json.loads((RUN / "stages" / f"extract-{index}-input.json").read_text(encoding="utf-8"))
        window = json.loads(package["request"]["user_input"])
        allowed = {item["segment"]["id"] for item in window["segments"]}
        candidate = RequirementCandidate.model_validate(json.loads(response["content"]))
        candidate, _ = canonicalize_candidate_sources(candidate, documents, allowed_segment_ids=allowed)
        candidates.append(candidate)
    return candidates


def fixed_fragment(chunk: list[RequirementCandidate], documents: list[DocumentIR]) -> dict:
    requirements, trace, local_maps = [], {}, []
    counter = 0
    for candidate in chunk:
        mapping = {}
        for item in candidate.requirements:
            counter += 1
            identifier = f"LOCAL-{counter:03d}"
            mapping[item.id] = identifier
            payload = item.model_dump(mode="json")
            payload["id"] = identifier
            requirement = RequirementItem.model_validate(payload)
            requirements.append(requirement)
            trace[identifier] = [source.segment_id for source in requirement.source_evidence if source.segment_id]
        local_maps.append(mapping)
    source = documents[0].source
    parsed = ParsedRequirements(
        schema_version="2.0",
        source={"path": source.path, "sha256": source.sha256, "name": source.name,
                "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        requirements=requirements,
        trace_index=trace,
    )
    return RequirementBaseline(schema_version="requirement-baseline/v1", parsed=parsed).model_dump(mode="json")


class FixedGateway:
    def __init__(self, stage: str, payloads: dict, requests: list):
        self.stage, self.payloads, self.requests = stage, payloads, requests

    def run(self, request):
        self.requests.append(request)
        payload = deepcopy(self.payloads[self.stage])
        return AgentResponse(status="succeeded", structured_output=payload,
                             raw_response={"stage": self.stage, "payload": payload},
                             provider="fixed", model="fixed-v5",
                             usage=AgentUsage(input_tokens=10, output_tokens=5))


def main() -> None:
    documents = [DocumentIR.model_validate(item) for item in json.loads((RUN / "document-ir.json").read_text(encoding="utf-8"))]
    candidates = load_candidates(documents)
    payloads = {}
    for index in range(0, len(candidates), 2):
        payloads[f"consolidate-{index // 2}"] = fixed_fragment(candidates[index:index + 2], documents)
    payloads["reconcile"] = {
        "schema_version": "requirement-reconciliation/v1", "merges": [], "conflicts": [], "ambiguities": [],
    }
    requests, usage = [], {"agent_calls": 0, "input_tokens": 0, "output_tokens": 0,
                           "token_usage_complete": True, "violations": [], "calls": []}
    limits = {"max_agent_calls": 48, "max_input_tokens": 2_000_000, "max_output_tokens": 500_000}

    def factory(stage):
        return BudgetedGateway(FixedGateway(stage, payloads, requests), usage, limits)

    skill = SkillRegistry.from_file("configs/skills.yaml").resolve("requirement-analysis")
    workflow = RequirementAnalysisWorkflow(factory, skill, max_consolidation_candidates=2,
                                           max_verification_requirements=40, max_agent_input_chars=450_000)
    prompts = {name: ((Path("prompts/requirement-analysis") / name).read_text(encoding="utf-8"), "hash")
               for name in ("consolidator-v1.md", "consolidator-fragment-v1.md", "reconciliation-v1.md")}
    records = ([], [])
    baseline, fragments, _ = workflow._consolidate(candidates, documents, prompts, records)
    baseline_hash = digest(canonical_json(baseline.model_dump(mode="json")))
    for index in range(0, len(baseline.parsed.requirements), 40):
        chunk = baseline.parsed.requirements[index:index + 40]
        payloads[f"verify-{index // 40}"] = {
            "schema_version": "verification-result/v1", "baseline_sha256": baseline_hash,
            "method": "semantic", "findings": [
                {"requirement_id": item.id, "status": "supported", "code": "FIXED",
                 "message": "仅验证分块覆盖", "segment_ids": []} for item in chunk
            ],
        }
    verification = workflow._semantic_verify(
        baseline, documents,
        Path("prompts/requirement-analysis/semantic-verifier-v1.md").read_text(encoding="utf-8"), records,
    )
    input_sizes = [len(item.user_input) + len(item.system_context or "") for item in requests]
    result = {
        "schema_version": "chunking-verification/v1",
        "source_run": str(RUN),
        "formal_score": None,
        "model_calls": 0,
        "candidate_batches": len(candidates),
        "candidate_requirements": sum(len(item.requirements) for item in candidates),
        "consolidation_fragments": len(fragments),
        "fragment_requirement_counts": [len(item.parsed.requirements) for item in fragments],
        "final_requirement_count": len(baseline.parsed.requirements),
        "verification_chunk_count": sum(stage.startswith("verify-") for stage in payloads),
        "verified_requirement_count": len(verification.findings),
        "verified_unique_requirement_count": len({item.requirement_id for item in verification.findings}),
        "max_request_chars": max(input_sizes),
        "request_limit_chars": workflow.max_agent_input_chars,
        "all_requests_within_limit": all(size <= workflow.max_agent_input_chars for size in input_sizes),
        "max_fragment_requirements": max(len(item.parsed.requirements) for item in fragments),
        "max_verification_findings": max(len(payload["findings"]) for stage, payload in payloads.items()
                                          if stage.startswith("verify-")),
        "budget_usage": usage,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
