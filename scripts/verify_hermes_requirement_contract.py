"""最小 Hermes 结构化响应验证；不记录凭据或原始业务响应。"""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path

from testing_platform.domain.analysis import RequirementCandidate
from testing_platform.infrastructure.hermes.gateway import (
    HermesRuntimeOptions, apply_hermes_profile, create_hermes_agent_gateway,
)
from testing_platform.infrastructure.hermes.skill_registry import SkillRegistry
from testing_platform.ports.agent_gateway import AgentRequest, AgentTaskType, OutputSchemaName


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    registry = SkillRegistry.from_file(root / "configs" / "skills.yaml")
    skill = registry.resolve("requirement-analysis")
    skill_text = (skill.path / "SKILL.md").read_text(encoding="utf-8")
    extractor = (root / "prompts" / "requirement-analysis" / "section-extractor-v1.md").read_text(encoding="utf-8")
    previous_home = os.environ.get("HERMES_HOME")
    try:
        profile_path = apply_hermes_profile("test-design-agent")
    finally:
        if previous_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = previous_home
    gateway = create_hermes_agent_gateway(HermesRuntimeOptions(max_turns=3, max_output_tokens=2500), skill_text)
    payload = {
        "segments": [{
            "document_id": "doc-contract",
            "file_sha256": "a" * 64,
            "segment": {
                "id": "seg-contract", "kind": "paragraph", "order": 0,
                "text": "数量必须为 1 至 9，包含边界。",
                "content_sha256": hashlib.sha256("数量必须为 1 至 9，包含边界。".encode()).hexdigest(),
                "locator": {"format": "markdown", "line_start": 1, "line_end": 1},
                "status": "parsed",
            },
        }],
    }
    schema = json.dumps(RequirementCandidate.model_json_schema(), ensure_ascii=False)
    request = AgentRequest(
        task_type=AgentTaskType.REQUIREMENT_ANALYSIS,
        user_input=json.dumps(payload, ensure_ascii=False),
        system_context=f"{extractor}\n\n输出必须通过以下 JSON Schema：\n{schema}",
        skill_name=skill.name, skill_version=skill.version,
        output_schema=OutputSchemaName.REQUIREMENT_CANDIDATE,
        model_id="runtime-configured", parameters={"temperature": 0, "purpose": "contract-spike"},
    )
    response = gateway.run(request)
    evidence = {
        "hermes_version": metadata.version("hermes-agent"),
        "profile_resolution_succeeded": bool(profile_path),
        "skill": {"name": skill.name, "version": skill.version, "path": str(skill.path)},
        "status": response.status,
        "provider": response.provider,
        "model": response.model,
        "structured_output_valid": response.structured_output is not None,
        "content_sha256": hashlib.sha256(response.content.encode("utf-8")).hexdigest(),
        "error": response.error.model_dump(mode="json") if response.error else None,
    }
    output = root / "artifacts" / "requirement-analysis" / "hermes-spike" / "result.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if response.structured_output is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
