from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "prepare_software_exploration_s2", ROOT / "scripts/prepare_software_exploration_s2.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_every_miniorder_requirement_has_one_truth_classification() -> None:
    ids = [f"REQ-{index:03d}" for index in range(1, 53)]
    statuses = [MODULE.expected_status(requirement_id) for requirement_id in ids]
    assert statuses.count("MAPPED") == 19
    assert statuses.count("PARTIALLY_MAPPED") == 27
    assert statuses.count("NOT_UI_OBSERVABLE") == 6


def test_every_miniorder_requirement_has_an_evidence_profile() -> None:
    for index in range(1, 53):
        area, controls, route = MODULE.evidence_profile(f"REQ-{index:03d}")
        assert area
        assert route
        if area != "non_gui":
            assert controls


def test_frozen_source_hashes_match_repository() -> None:
    assert MODULE.sha256(ROOT / "artifacts/miniorder/blackbox-run/MiniOrder.exe") == MODULE.EXPECTED_EXE_SHA256
    assert MODULE.sha256(ROOT / "docs/miniorder/MiniOrder-Requirements.md") == MODULE.EXPECTED_REQUIREMENTS_SHA256
