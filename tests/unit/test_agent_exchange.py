from __future__ import annotations

import json

from testing_platform.application.services.agent_exchange import (
    build_agent_audit, export_agent_input, import_structured_response,
)
from testing_platform.domain.requirements import ParsedRequirements
from testing_platform.infrastructure.hermes.schema_registry import resolve_output_schema
from testing_platform.ports.agent_gateway import (
    AgentRequest, AgentResponse, AgentRunStatus, AgentTaskType, OutputSchemaName,
)


class FakeGateway:
    def __init__(self):
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return AgentResponse(status="succeeded", content='{"schema_version":"1.0","source":{"path":"x"},"requirements":[]}',
                             raw_response={"id": "raw-1"}, provider="fake", model="fake-model")


def test_requirement_types_registry_export_import_and_audit():
    request = AgentRequest(
        task_type=AgentTaskType.REQUIREMENT_ANALYSIS_REPAIR, user_input="修复结构",
        skill_name="requirement-analysis", skill_version="1.0.0",
        output_schema=OutputSchemaName.PARSED_REQUIREMENTS, model_id="requested-model",
        parameters={"temperature": 0}, attempt=2,
        human_interventions=["人工导入结构化响应"], execution_mode="import",
    )
    gateway = FakeGateway(); response = gateway.run(request)
    package = export_agent_input(request)
    imported = import_structured_response(response.content, resolve_output_schema(request.output_schema),
                                          model_id="fake-model")
    audit = build_agent_audit(request, response)
    assert package.request == request and package.request_sha256 == export_agent_input(request).request_sha256
    assert imported.status == AgentRunStatus.SUCCEEDED
    assert ParsedRequirements.model_validate(imported.structured_output).schema_version == "1.0"
    assert audit.model_id == "fake-model" and audit.skill_version == "1.0.0"
    assert audit.parameters == {"temperature": 0} and audit.attempt == 2
    assert audit.human_interventions and len(audit.raw_response_sha256) == 64
    assert build_agent_audit(request, response) == audit


def test_invalid_import_is_failed_not_product_result():
    response = import_structured_response("{}", ParsedRequirements)
    assert response.status == AgentRunStatus.FAILED
    assert response.error.code == "INVALID_STRUCTURED_RESPONSE"
