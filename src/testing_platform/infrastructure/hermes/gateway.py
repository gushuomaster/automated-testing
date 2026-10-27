"""Hermes Adapter；Hermes 依赖仅在创建真实运行时或调用 Fake Agent 时进入。"""
from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from testing_platform.application.services.agent_exchange import import_structured_response
from testing_platform.infrastructure.hermes.schema_registry import resolve_output_schema
from testing_platform.ports.agent_gateway import AgentError, AgentGateway, AgentRequest, AgentResponse, AgentRunStatus


class HermesRuntimeOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str = ""
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    max_turns: int = Field(default=8, gt=0)
    max_output_tokens: int = Field(default=0, ge=0)


class HermesAgentGateway(AgentGateway):
    def __init__(self, agent: Any) -> None:
        self._agent = agent

    def run(self, request: AgentRequest) -> AgentResponse:
        prompt = request.user_input
        if request.system_context:
            prompt = f"{request.system_context}\n\n{prompt}"
        result = self._agent.run_conversation(prompt)
        if not isinstance(result, dict):
            return AgentResponse(status=AgentRunStatus.FAILED,
                                 error=AgentError(code="INVALID_HERMES_RESULT", message="Hermes 没有返回映射结果。"))
        response = AgentResponse.from_mapping(result)
        if response.status == AgentRunStatus.SUCCEEDED and request.output_schema:
            imported = import_structured_response(response.content, resolve_output_schema(request.output_schema),
                                                  provider=response.provider, model_id=response.model)
            imported.raw_response = response.raw_response
            imported.usage = response.usage
            imported.tool_calls = response.tool_calls
            return imported
        return response


def apply_hermes_profile(profile: str) -> str:
    if not profile.strip():
        return os.environ.get("HERMES_HOME", "")
    from hermes_cli.profiles import resolve_profile_env
    path = str(resolve_profile_env(profile.strip()))
    os.environ["HERMES_HOME"] = path
    return path


def create_hermes_agent_gateway(options: HermesRuntimeOptions, system_prompt: str) -> HermesAgentGateway:
    """使用 Hermes 官方解析器创建真实 Gateway；不打印或持久化密钥。"""
    apply_hermes_profile(options.profile)
    from hermes_cli.config import load_config
    from hermes_cli.models import get_default_model_for_provider
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from run_agent import AIAgent

    runtime = resolve_runtime_provider(requested=options.provider or None,
                                       explicit_api_key=options.api_key or None,
                                       explicit_base_url=options.base_url or None)
    config = load_config()
    configured = config.get("model", {})
    configured_model = (configured.get("default") or configured.get("model") or "") if isinstance(configured, dict) else str(configured or "")
    provider = str(runtime.get("provider") or "")
    model = options.model or str(runtime.get("model") or "") or configured_model or get_default_model_for_provider(provider) or ""
    if not model:
        raise RuntimeError("Hermes 未解析到模型")
    base_url = str(runtime.get("base_url") or "")
    api_key = str(runtime.get("api_key") or "")
    if not api_key and base_url and not any(local in base_url for local in ("localhost", "127.0.0.1")):
        raise RuntimeError("Hermes 未解析到远程运行时所需凭据")
    agent = AIAgent(model=model, api_key=api_key or "no-key-required", base_url=base_url,
                    provider=provider, api_mode=runtime.get("api_mode"),
                    acp_command=runtime.get("command"), acp_args=list(runtime.get("args") or []),
                    credential_pool=runtime.get("credential_pool"), max_iterations=options.max_turns,
                    max_tokens=options.max_output_tokens or None, enabled_toolsets=[], quiet_mode=True,
                    platform="cli", skip_memory=True, ephemeral_system_prompt=system_prompt)
    return HermesAgentGateway(agent)
