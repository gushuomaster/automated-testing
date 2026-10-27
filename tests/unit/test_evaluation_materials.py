import json
from pathlib import Path

import pytest

from testing_platform.domain.requirements import ParsedRequirements
from testing_platform.evaluation.materials import MaterialRoles, verify_materials
from testing_platform.evaluation.regression import quick_regression


def test_material_roles_hashes_and_only_independent_material_enters_formal_score():
    root = Path(__file__).resolve().parents[2]
    manifest = MaterialRoles.model_validate_json((root / "evaluation/requirement-analysis/material-roles.json").read_text(encoding="utf-8"))
    verified = verify_materials(manifest, root)
    assert len(verified) == 7
    assert manifest.formal_material == "formal-v6-material-a"
    dds = next(item for item in manifest.materials if item.id == "formal-dds-mqtt-v1-2-2")
    assert dds.role == "regression" and not dds.allowed_in_formal_score
    formal = next(item for item in manifest.materials if item.id == manifest.formal_material)
    assert formal.role == "formal" and formal.allowed_in_formal_score
    assert sum(item.allowed_in_formal_score for item in manifest.materials) == 1


def test_quick_regression_is_not_formal_semantic_score():
    parsed = ParsedRequirements.model_validate({"source": {"path": "fixture.md"}, "requirements": [
        {"id": "REQ-001", "source_evidence": [{"path": "fixture.md", "segment_id": "s1"}]},
        {"id": "REQ-002", "source_evidence": [{"path": "fixture.md", "segment_id": "s2"}]},
    ]})
    result = quick_regression(parsed, ["REQ-001", "REQ-002"], ["24 小时", "重试 3 次"])
    assert result.passed and result.limitations
    failed = quick_regression(parsed, ["REQ-001", "REQ-003"], ["REQ-002"])
    assert not failed.passed and failed.missing_ids == ["REQ-003"] and failed.unexpected_ids == ["REQ-002"]
