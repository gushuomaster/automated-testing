from __future__ import annotations

from pydantic import BaseModel

from testing_platform.domain.analysis import (
    RequirementBaseline, RequirementCandidate, RequirementReconciliation, VerificationResult,
)
from testing_platform.domain.requirements import ParsedRequirements
from testing_platform.ports.agent_gateway import OutputSchemaName


SCHEMA_REGISTRY: dict[OutputSchemaName, type[BaseModel]] = {
    OutputSchemaName.PARSED_REQUIREMENTS: ParsedRequirements,
    OutputSchemaName.REQUIREMENT_CANDIDATE: RequirementCandidate,
    OutputSchemaName.REQUIREMENT_BASELINE: RequirementBaseline,
    OutputSchemaName.REQUIREMENT_RECONCILIATION: RequirementReconciliation,
    OutputSchemaName.VERIFICATION_RESULT: VerificationResult,
}


def resolve_output_schema(name: OutputSchemaName) -> type[BaseModel]:
    try:
        return SCHEMA_REGISTRY[name]
    except KeyError as exc:
        raise LookupError(f"未注册输出 Schema：{name}") from exc
