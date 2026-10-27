from pathlib import Path

from testing_platform.infrastructure.hermes.gateway import HermesAgentGateway
from testing_platform.infrastructure.hermes.skill_registry import SkillRegistry
from testing_platform.ports.agent_gateway import AgentRequest, AgentRunStatus, AgentTaskType, OutputSchemaName


class FakeHermes:
    def __init__(self, content): self.content, self.prompts = content, []
    def run_conversation(self, prompt):
        self.prompts.append(prompt)
        return {"final_response": self.content, "failed": False, "provider": "fake", "model": "fake-model"}


def test_registry_and_structured_gateway_contract():
    registry = SkillRegistry.from_file(Path("configs/skills.yaml"))
    definition = registry.resolve("requirement-analysis")
    assert definition.version == "1.0.0" and (definition.path / "SKILL.md").is_file()
    fake = FakeHermes('{"schema_version":"1.0","source":{"path":"需求.md"},"requirements":[]}')
    response = HermesAgentGateway(fake).run(AgentRequest(
        task_type=AgentTaskType.REQUIREMENT_ANALYSIS, user_input="输入", system_context="系统规则",
        skill_name=definition.name, skill_version=definition.version,
        output_schema=OutputSchemaName.PARSED_REQUIREMENTS,
    ))
    assert response.status == AgentRunStatus.SUCCEEDED
    assert response.structured_output["schema_version"] == "1.0"
    assert fake.prompts == ["系统规则\n\n输入"]


def test_gateway_rejects_structurally_invalid_answer():
    response = HermesAgentGateway(FakeHermes("{}")).run(AgentRequest(
        task_type="requirement_analysis", user_input="输入", output_schema="ParsedRequirementsProposal"))
    assert response.status == AgentRunStatus.FAILED
    assert response.error.code == "INVALID_STRUCTURED_RESPONSE"
