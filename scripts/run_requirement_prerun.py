"""运行不计分校准/开发预演，并按层保存原始结果和锁。"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from uuid import uuid4

from testing_platform.application.workflows.requirement_analysis import (
    AgentStepFailure, RequirementAnalysisWorkflow, persist_requirement_analysis_run,
)
from testing_platform.domain.analysis import RequirementBaseline, RequirementCandidate, VerificationResult
from testing_platform.domain.documents import DocumentIR, InputManifest, digest
from testing_platform.evaluation.protocol import ReportLock, lock_files, verify_lock
from testing_platform.infrastructure.artifacts.local_artifact_store import LocalArtifactStore
from testing_platform.infrastructure.documents.ingestion import create_manifest, ingest_manifest
from testing_platform.infrastructure.hermes.gateway import HermesRuntimeOptions, create_hermes_agent_gateway
from testing_platform.infrastructure.hermes.skill_registry import SkillRegistry
from testing_platform.ports.agent_gateway import AgentGateway, AgentRequest, AgentResponse


class BudgetExceeded(RuntimeError):
    pass


class BudgetedGateway(AgentGateway):
    def __init__(self, gateway: AgentGateway, usage: dict, limits: dict) -> None:
        self.gateway, self.usage, self.limits = gateway, usage, limits

    def run(self, request: AgentRequest) -> AgentResponse:
        if self.usage["agent_calls"] >= self.limits["max_agent_calls"]:
            raise BudgetExceeded("正式运行的 Agent 调用次数已达到冻结上限")
        if (self.usage["input_tokens"] >= self.limits["max_input_tokens"]
                or self.usage["output_tokens"] >= self.limits["max_output_tokens"]):
            raise BudgetExceeded("正式运行的累计 token 预算已耗尽")
        self.usage["agent_calls"] += 1
        response = self.gateway.run(request)
        usage = response.usage.model_dump(mode="json") if response.usage else {}
        if not usage and isinstance(response.raw_response, dict):
            usage = response.raw_response
        input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
        output_tokens = usage.get("output_tokens") or usage.get("completion_tokens")
        if input_tokens is None or output_tokens is None:
            self.usage["token_usage_complete"] = False
        else:
            self.usage["input_tokens"] += int(input_tokens)
            self.usage["output_tokens"] += int(output_tokens)
        self.usage["calls"].append({
            "stage": request.parameters.get("stage", ""),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        })
        if self.usage["input_tokens"] > self.limits["max_input_tokens"]:
            self.usage["violations"].append("INPUT_TOKENS_EXCEEDED")
        if self.usage["output_tokens"] > self.limits["max_output_tokens"]:
            self.usage["violations"].append("OUTPUT_TOKENS_EXCEEDED")
        if self.usage["violations"]:
            raise BudgetExceeded("正式运行超出冻结的累计 token 预算")
        return response


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def response_payload(path: Path) -> object:
    snapshot = read_json(path)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("content"), str):
        raise ValueError(f"阶段响应缺少 content：{path}")
    return json.loads(snapshot["content"])


def load_revision_parent(parent: Path, role: str) -> tuple[
    list[DocumentIR], InputManifest, list[RequirementCandidate], RequirementBaseline, VerificationResult, dict
]:
    parent = parent.resolve(strict=True)
    lock = ReportLock.model_validate(read_json(parent / "report-lock.json"))
    failures = verify_lock(lock, parent)
    verification = {
        "parent_run": str(parent),
        "parent_lock_sha256": lock.lock_sha256,
        "verified": not failures,
        "failures": failures,
    }
    if failures:
        raise ValueError(f"父运行报告锁校验失败：{failures}")
    failure = read_json(parent / "failure.json")
    if not isinstance(failure, dict) or failure.get("layer") != "repair":
        raise ValueError("仅允许从 repair 层失败的父运行恢复")
    parent_start = read_json(parent / "run-start.json")
    if not isinstance(parent_start, dict) or parent_start.get("role") != role:
        raise ValueError("恢复角色必须与父运行一致")

    documents_raw = read_json(parent / "document-ir.json")
    manifest = InputManifest.model_validate(read_json(parent / "input-manifest.json"))
    if not isinstance(documents_raw, list):
        raise ValueError("父运行 document-ir.json 不是列表")
    documents = [DocumentIR.model_validate(item) for item in documents_raw]
    consolidate_input = read_json(parent / "stages" / "consolidate-input.json")
    if not isinstance(consolidate_input, dict):
        raise ValueError("父运行归并输入无效")
    request = consolidate_input.get("request")
    if not isinstance(request, dict) or not isinstance(request.get("user_input"), str):
        raise ValueError("父运行归并输入缺少 request.user_input")
    consolidation_payload = json.loads(request["user_input"])
    candidates = [RequirementCandidate.model_validate(item) for item in consolidation_payload["candidates"]]
    initial = RequirementBaseline.model_validate(response_payload(parent / "stages" / "consolidate-response.json"))
    semantic = VerificationResult.model_validate(response_payload(parent / "stages" / "verify-response.json"))
    return documents, manifest, candidates, initial, semantic, verification


def prompt_hashes(root: Path) -> dict[str, str]:
    names = ("repair-v1.md", "semantic-verifier-v1.md")
    return {name: digest((root / "prompts" / "requirement-analysis" / name).read_bytes()) for name in names}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("--resume-from", type=Path,
                        help="从已锁定且在 repair 层失败的预演运行继续修订")
    parser.add_argument("--role", choices=("calibration", "development", "formal"), required=True)
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/requirement-analysis/preruns"))
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--max-turns", type=int, default=4)
    parser.add_argument("--max-output-tokens", type=int, default=8000)
    parser.add_argument("--max-agent-calls", type=int, default=25)
    parser.add_argument("--max-input-tokens-total", type=int, default=400000)
    parser.add_argument("--max-output-tokens-total", type=int, default=300000)
    parser.add_argument("--max-window-chars", type=int, default=12000)
    parser.add_argument("--max-window-segments", type=int, default=12)
    parser.add_argument("--max-agent-input-chars", type=int, default=450000)
    parser.add_argument("--max-consolidation-candidates", type=int, default=2)
    parser.add_argument("--max-verification-requirements", type=int, default=40)
    parser.add_argument("--disable-revision", action="store_true")
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if (args.input is None) == (args.resume_from is None):
        parser.error("必须且只能提供 input 或 --resume-from 之一")
    positive_options = {
        "超时": args.timeout_seconds,
        "最大轮数": args.max_turns,
        "单次最大输出 token": args.max_output_tokens,
        "最大 Agent 调用数": args.max_agent_calls,
        "总输入 token 预算": args.max_input_tokens_total,
        "总输出 token 预算": args.max_output_tokens_total,
        "窗口最大字符数": args.max_window_chars,
        "窗口最大片段数": args.max_window_segments,
        "Agent 阶段输入字符上限": args.max_agent_input_chars,
        "归并块最大候选批数": args.max_consolidation_candidates,
        "核验块最大需求数": args.max_verification_requirements,
    }
    for label, value in positive_options.items():
        if value <= 0:
            parser.error(f"{label}必须大于零")
    run_id = args.worker_output.name if args.worker_output else str(uuid4())
    output = args.worker_output or (args.output_root / args.role / run_id).resolve()
    if args.worker_output is None:
        parent_verification = None
        if args.resume_from is not None:
            _, _, _, _, _, parent_verification = load_revision_parent(args.resume_from, args.role)
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / "run-start.json", {"run_id": run_id, "role": args.role,
                                              "mode": "revision-resume" if args.resume_from else "full",
                                              "parent_run": str(args.resume_from.resolve()) if args.resume_from else None,
                                              "parent_lock_sha256": parent_verification["parent_lock_sha256"] if parent_verification else None,
                                              "timeout_seconds": args.timeout_seconds,
                                              "runtime": {"adapter": "Hermes", "max_turns": args.max_turns,
                                                          "max_output_tokens_per_call": args.max_output_tokens,
                                                          "max_agent_calls": args.max_agent_calls,
                                                          "max_input_tokens_total": args.max_input_tokens_total,
                                                          "max_output_tokens_total": args.max_output_tokens_total,
                                                          "max_agent_input_chars": args.max_agent_input_chars,
                                                          "revision_enabled": not args.disable_revision},
                                              "window": {"max_chars": args.max_window_chars,
                                                         "max_segments": args.max_window_segments},
                                              "chunking": {
                                                  "max_consolidation_candidates": args.max_consolidation_candidates,
                                                  "max_verification_requirements": args.max_verification_requirements,
                                              },
                                              "prompt_hashes": prompt_hashes(root) if args.resume_from else None,
                                              "formal_score": None})
        command = [sys.executable, str(Path(__file__).resolve()),
                   "--role", args.role, "--worker-output", str(output),
                   "--timeout-seconds", str(args.timeout_seconds),
                   "--max-turns", str(args.max_turns),
                   "--max-output-tokens", str(args.max_output_tokens),
                   "--max-agent-calls", str(args.max_agent_calls),
                   "--max-input-tokens-total", str(args.max_input_tokens_total),
                   "--max-output-tokens-total", str(args.max_output_tokens_total),
                   "--max-window-chars", str(args.max_window_chars),
                   "--max-window-segments", str(args.max_window_segments),
                   "--max-agent-input-chars", str(args.max_agent_input_chars),
                   "--max-consolidation-candidates", str(args.max_consolidation_candidates),
                   "--max-verification-requirements", str(args.max_verification_requirements)]
        if args.disable_revision:
            command.append("--disable-revision")
        if args.resume_from:
            command.extend(["--resume-from", str(args.resume_from.resolve())])
        else:
            command.insert(2, str(args.input.resolve()))
        with (output / "runtime.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       env=os.environ | {"PYTHONUTF8": "1"})
            try:
                code = process.wait(timeout=args.timeout_seconds)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                write_json(output / "failure.json", {"status": "timeout", "layer": "agent-runtime",
                                                       "timeout_seconds": args.timeout_seconds,
                                                       "cause": "尚未确定；运行已到预注册总墙钟时间上限",
                                                       "formal_score": None})
                code = 2
        locked = lock_files([p for p in output.rglob("*") if p.is_file() and p.name != "report-lock.json"], output)
        write_json(output / "report-lock.json", locked.model_dump(mode="json"))
        print(json.dumps({"exit_code": code, "output": str(output)}, ensure_ascii=False))
        return code
    try:
        budget_usage = {"agent_calls": 0, "input_tokens": 0, "output_tokens": 0,
                        "token_usage_complete": True, "violations": [], "calls": []}
        budget_limits = {"max_agent_calls": args.max_agent_calls,
                         "max_input_tokens": args.max_input_tokens_total,
                         "max_output_tokens": args.max_output_tokens_total}
        if args.resume_from:
            documents, manifest, candidates, initial, semantic, parent_verification = load_revision_parent(
                args.resume_from, args.role
            )
            write_json(output / "parent-lock-verification.json", parent_verification)
            ingestion = None
        else:
            manifest = create_manifest([args.input], role=args.role,
                                       config={"workflow": "requirement-analysis/v1", "revision_limit": 1})
            ingestion = ingest_manifest(manifest)
            documents = ingestion.documents
            write_json(output / "ingestion-summary.json", ingestion.summary.model_dump(mode="json"))
            write_json(output / "input-manifest.json", manifest.model_dump(mode="json"))
            write_json(output / "document-ir.json", [d.model_dump(mode="json") for d in documents])
        skill = SkillRegistry.from_file(root / "configs" / "skills.yaml").resolve("requirement-analysis")

        def factory(stage):
            prompt = f"你是需求分析工作流的 {stage} 阶段。阶段之间使用独立上下文。"
            gateway = create_hermes_agent_gateway(
                HermesRuntimeOptions(max_turns=args.max_turns, max_output_tokens=args.max_output_tokens), prompt
            )
            return BudgetedGateway(gateway, budget_usage, budget_limits)

        workflow = RequirementAnalysisWorkflow(
            factory, skill, root / "prompts" / "requirement-analysis",
            max_window_chars=args.max_window_chars,
            max_window_segments=args.max_window_segments,
            max_agent_input_chars=args.max_agent_input_chars,
            max_consolidation_candidates=args.max_consolidation_candidates,
            max_verification_requirements=args.max_verification_requirements,
            event_sink=lambda name, payload: write_json(output / "stages" / (name + ".json"), payload),
        )
        if args.resume_from:
            run = workflow.resume_revision(documents, manifest, candidates, initial, semantic)
        else:
            run = workflow.run(documents, manifest, allow_revision=not args.disable_revision)
        store = LocalArtifactStore(output / "artifacts")
        references = persist_requirement_analysis_run(run, store, uuid4())
        final = run.active_baseline.parsed
        layer_summary = {
            "run_id": run_id, "role": args.role, "input": manifest.files[0].model_dump(mode="json"),
            "mode": "revision-resume" if args.resume_from else "full",
            "parent_run": str(args.resume_from.resolve()) if args.resume_from else None,
            "parsing": {"status": documents[0].status, "segments": len(documents[0].segments),
                        "issues": [item.model_dump(mode="json") for item in documents[0].issues]},
            "extraction": {"candidate_batches": len(run.candidates),
                           "candidate_requirements": sum(len(item.requirements) for item in run.candidates),
                           "baseline_requirements": len(final.requirements),
                           "ambiguities": len(final.ambiguities), "conflicts": len(final.conflicts),
                           "recommendations": len(final.recommendations)},
            "verification": {"deterministic": [item.model_dump(mode="json") for item in run.deterministic_verifications],
                             "semantic": [item.model_dump(mode="json") for item in run.semantic_verifications],
                             "revision_count": run.revision_count},
            "agent": {"calls": len(run.audits), "audits": [item.model_dump(mode="json") for item in run.audits]},
            "budget_usage": budget_usage,
            "scoring": {
                "included_in_formal_score": args.role == "formal",
                "passed": None,
                "reason": ("正式运行等待评估侧锁定原始报告后评分"
                           if args.role == "formal"
                           else "校准/开发预演没有冻结人工真值，按协议不计算正式成绩"),
            },
        }
        write_json(output / "layer-summary.json", layer_summary)
        locked_paths = [store.resolve(item) for item in references] + [output / "layer-summary.json"]
        if args.resume_from:
            locked_paths.append(output / "parent-lock-verification.json")
        else:
            locked_paths.append(output / "ingestion-summary.json")
        lock = lock_files(locked_paths, output)
        write_json(output / "report-lock.json", lock.model_dump(mode="json"))
        write_json(output / "status.json", {"status": "completed", "run_id": run_id})
        print(json.dumps({"status": "completed", "output": str(output), "summary": layer_summary}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        evidence = {"status": "failed", "layer": "workflow", "error_type": type(exc).__name__,
                    "message": str(exc), "traceback": traceback.format_exc()}
        if "budget_usage" in locals():
            evidence["budget_usage"] = budget_usage
        if isinstance(exc, AgentStepFailure):
            evidence.update({"layer": exc.stage, "input_package": exc.package.model_dump(mode="json"),
                             "audit": exc.audit.model_dump(mode="json"),
                             "cause_type": type(exc.cause).__name__, "cause": str(exc.cause)})
        write_json(output / "failure.json", evidence)
        print(json.dumps({"status": "failed", "output": str(output), "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
