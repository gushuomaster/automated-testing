"""Agent 输入包、结构化响应导入和不含原文的审计记录。"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from testing_platform.domain.documents import canonical_json, digest
from testing_platform.ports.agent_gateway import (
    AgentInputPackage, AgentRequest, AgentResponse, AgentRunAudit, AgentRunStatus,
)


def _hashable(value: Any) -> bytes:
    try:
        return canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise TypeError("原始响应不可按 JSON 无损保存，不能生成可复核审计哈希") from exc


def export_agent_input(request: AgentRequest) -> AgentInputPackage:
    payload = request.model_dump(mode="json")
    return AgentInputPackage(schema_version="agent-input/v1", request=request,
                             request_sha256=digest(canonical_json(payload)))


def import_structured_response(raw: str | bytes, model: type[BaseModel], *,
                               provider: str = "manual-import", model_id: str = "") -> AgentResponse:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig", errors="strict")
    try:
        payload = json.loads(raw)
        validated = model.model_validate(payload)
    except Exception as exc:
        return AgentResponse(status=AgentRunStatus.FAILED, content=raw,
                             raw_response={"content": raw},
                             error={"code": "INVALID_STRUCTURED_RESPONSE", "message": str(exc)},
                             provider=provider, model=model_id)
    return AgentResponse(status=AgentRunStatus.SUCCEEDED, content=raw,
                         structured_output=validated.model_dump(mode="json"),
                         raw_response={"content": raw}, provider=provider, model=model_id)


def build_agent_audit(request: AgentRequest, response: AgentResponse) -> AgentRunAudit:
    package = export_agent_input(request)
    raw = response.raw_response if response.raw_response is not None else response.content
    return AgentRunAudit(
        schema_version="agent-run-audit/v1", task_type=request.task_type,
        execution_mode=request.execution_mode, model_id=response.model or request.model_id,
        provider=response.provider, skill_name=request.skill_name or "",
        skill_version=request.skill_version, parameters=request.parameters,
        attempt=request.attempt, human_interventions=request.human_interventions,
        request_sha256=package.request_sha256, raw_response_sha256=digest(_hashable(raw)),
        status=response.status,
    )
