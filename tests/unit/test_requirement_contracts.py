from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import sys

from jsonschema import Draft202012Validator, ValidationError as SchemaError
from pydantic import ValidationError
import pytest

from testing_platform.domain.analysis import RequirementBaseline
from testing_platform.domain.requirements import ParsedRequirements
from testing_platform.infrastructure.documents.ingestion import create_manifest, ingest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from export_requirement_schemas import MODELS, export


def baseline(tmp_path):
    path = tmp_path / "需求.md"; path.write_text("# 订单\n\n必须保存订单。", encoding="utf-8")
    ir = ingest(create_manifest([path], role="development").files[0])
    segment = ir.segments[-1]
    return {"schema_version": "2.0", "source": {"path": str(path), "sha256": ir.source.sha256},
            "requirements": [{"id": "R1", "target": "订单", "categories": ["functional"],
                              "description": "必须保存订单。", "expected_behavior": "订单被保存", "confidence": 1,
                              "source_evidence": [{"path": str(path), "sha256": ir.source.sha256,
                                                   "segment_id": segment.id, "locator": segment.locator.model_dump(),
                                                   "excerpt": segment.text}]}]}


def test_old_new_versions_and_rejected_fields(tmp_path):
    legacy = ParsedRequirements(source={"path": "old.md"}, requirements=[{"id": "R1"}])
    assert legacy.schema_version == "1.0"
    assert ParsedRequirements.model_validate(legacy.model_dump()) == legacy
    legacy_wire = legacy.legacy_payload()
    assert set(legacy_wire) == {"schema_version", "source", "requirements"}
    assert set(legacy_wire["requirements"][0]) == {"id"}
    s1_on_legacy = legacy.model_copy(deep=True)
    s1_on_legacy.requirements[0].target = "S1 对象"
    with pytest.raises(ValueError, match="扩展字段"):
        s1_on_legacy.legacy_payload()
    payload = baseline(tmp_path)
    parsed = ParsedRequirements.model_validate(payload)
    assert ParsedRequirements.model_validate_json(parsed.model_dump_json()) == parsed
    with pytest.raises(ValueError): parsed.legacy_payload()
    for mutate in (lambda p: p.update(schema_version="9.0"),
                   lambda p: p["requirements"].append(p["requirements"][0]),
                   lambda p: p["requirements"][0].update(unknown="x"),
                   lambda p: p["requirements"][0].update(target=""),
                   lambda p: p["requirements"][0].update(information_nature="assumption"),
                   lambda p: p.update(cases=[])):
        bad = deepcopy(payload); mutate(bad)
        with pytest.raises(ValidationError): ParsedRequirements.model_validate(bad)


def test_exported_schemas_reject_missing_type_and_version(tmp_path):
    export(tmp_path / "schemas")
    valid_baseline = RequirementBaseline(schema_version="requirement-baseline/v1", parsed=baseline(tmp_path)).model_dump(mode="json")
    manifest = create_manifest([tmp_path / "需求.md"], role="development")
    examples = [manifest.model_dump(mode="json"), ingest(manifest.files[0]).model_dump(mode="json"),
                {"schema_version": "requirement-candidate/v1", "requirements": []}, valid_baseline,
                {"schema_version": "requirement-reconciliation/v1", "merges": [], "conflicts": [], "ambiguities": []},
                {"schema_version": "verification-result/v1", "baseline_sha256": "a" * 64, "method": "semantic", "findings": []},
                {"schema_version": "evaluation-result/v1", "role": "development", "report_sha256": "a" * 64,
                 "metrics": {}, "critical_errors": [], "unresolved": [], "passed": None}]
    for model, payload in zip(MODELS, examples):
        schema = json.loads((tmp_path / "schemas" / (payload["schema_version"].replace("/", "-") + ".schema.json")).read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema); validator.check_schema(schema)
        validator.validate(payload); model.model_validate(payload)
        for bad in ({**payload, "schema_version": "unknown/v99"}, {**payload, "unexpected": True}):
            with pytest.raises(SchemaError): validator.validate(bad)
        key = schema["required"][0]
        bad = deepcopy(payload); del bad[key]
        with pytest.raises(SchemaError): validator.validate(bad)
        bad = deepcopy(payload); del bad["schema_version"]
        with pytest.raises(SchemaError): validator.validate(bad)
        bad = deepcopy(payload); bad[key] = 42
        with pytest.raises(SchemaError): validator.validate(bad)
