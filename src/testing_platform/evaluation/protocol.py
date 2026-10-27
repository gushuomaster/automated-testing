from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from testing_platform.domain.documents import StrictModel, canonical_json, digest


class Budget(StrictModel):
    max_agent_calls: int = Field(gt=0)
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    max_revisions: int = Field(default=1, ge=0, le=1)


class BudgetUsage(StrictModel):
    agent_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    revisions: int = Field(ge=0)


def budget_violations(budget: Budget, usage: BudgetUsage) -> list[str]:
    checks = (("AGENT_CALLS_EXCEEDED", usage.agent_calls, budget.max_agent_calls),
              ("INPUT_TOKENS_EXCEEDED", usage.input_tokens, budget.max_input_tokens),
              ("OUTPUT_TOKENS_EXCEEDED", usage.output_tokens, budget.max_output_tokens),
              ("REVISIONS_EXCEEDED", usage.revisions, budget.max_revisions))
    return [code for code, actual, maximum in checks if actual > maximum]


class FrozenProtocol(StrictModel):
    schema_version: Literal["formal-protocol/v1"]
    material_id: str
    material_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    truth_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    matching_rules_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_id: str
    skill_version: str
    prompt_hashes: dict[str, str]
    budget: Budget
    allowed_inputs: list[str]
    forbidden_path_fragments: list[str]
    frozen: bool = True


class IsolationFinding(StrictModel):
    code: str
    location: str
    detail: str


class IsolationReport(StrictModel):
    schema_version: Literal["isolation-report/v1"]
    findings: list[IsolationFinding]
    passed: bool


def audit_agent_input(value: object, protocol: FrozenProtocol) -> IsolationReport:
    findings = []
    forbidden_keys = {"truth", "ground_truth", "expected_matches", "score", "evaluation_log", "source_code"}

    def walk(item, location="$"):
        if isinstance(item, dict):
            for key, nested in item.items():
                if key.casefold() in forbidden_keys:
                    findings.append(IsolationFinding(code="FORBIDDEN_KEY", location=f"{location}.{key}", detail=key))
                walk(nested, f"{location}.{key}")
        elif isinstance(item, list):
            for index, nested in enumerate(item): walk(nested, f"{location}[{index}]")
        elif isinstance(item, str):
            normalized = item.replace("\\", "/").casefold()
            for fragment in protocol.forbidden_path_fragments:
                if fragment.replace("\\", "/").casefold() in normalized:
                    findings.append(IsolationFinding(code="FORBIDDEN_PATH", location=location, detail=fragment))
    walk(value)
    return IsolationReport(schema_version="isolation-report/v1", findings=findings, passed=not findings)


class LockedFile(StrictModel):
    path: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReportLock(StrictModel):
    schema_version: Literal["report-lock/v1"]
    files: list[LockedFile]
    lock_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def lock_files(paths: list[Path], root: Path) -> ReportLock:
    resolved_root = root.resolve(strict=True)
    files = []
    for path in sorted((item.resolve(strict=True) for item in paths), key=str):
        try:
            relative = path.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"锁定文件超出根目录：{path}") from exc
        data = path.read_bytes()
        files.append(LockedFile(path=relative.as_posix(), size_bytes=len(data), sha256=digest(data)))
    content_hash = digest(canonical_json([item.model_dump(mode="json") for item in files]))
    return ReportLock(schema_version="report-lock/v1", files=files, lock_sha256=content_hash)


def verify_lock(lock: ReportLock, root: Path) -> list[str]:
    failures = []
    if digest(canonical_json([item.model_dump(mode="json") for item in lock.files])) != lock.lock_sha256:
        failures.append("LOCK_MANIFEST_CHANGED")
    for item in lock.files:
        path = (root / item.path).resolve()
        try:
            path.relative_to(root.resolve(strict=True))
        except ValueError:
            failures.append("LOCK_PATH_OUTSIDE_ROOT:" + item.path)
            continue
        if not path.is_file() or path.stat().st_size != item.size_bytes or digest(path.read_bytes()) != item.sha256:
            failures.append(item.path)
    return failures
