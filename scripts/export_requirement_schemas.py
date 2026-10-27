"""由唯一模型生成可共享 JSON Schema，不手工维护第二份字段定义。"""
from pathlib import Path
import json

from testing_platform.domain.analysis import (
    EvaluationResult, RequirementBaseline, RequirementCandidate, RequirementReconciliation, VerificationResult,
)
from testing_platform.domain.documents import DocumentIR, InputManifest

MODELS = (InputManifest, DocumentIR, RequirementCandidate, RequirementBaseline, RequirementReconciliation,
          VerificationResult, EvaluationResult)


def export(root=Path("schemas/requirement-analysis")):
    root.mkdir(parents=True, exist_ok=True)
    for model in MODELS:
        schema = model.model_json_schema()
        name = next(iter(model.model_fields["schema_version"].annotation.__args__))
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"urn:testing-platform:{name}"
        (root / (name.replace("/", "-") + ".schema.json")).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    export()
