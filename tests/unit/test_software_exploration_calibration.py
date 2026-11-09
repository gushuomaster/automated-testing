from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.prepare_software_exploration_calibration import EXPERIMENT, prepare


def test_prepare_refuses_to_overwrite_existing_run(tmp_path: Path) -> None:
    existing = tmp_path / "artifacts/software-exploration/round-02"
    existing.mkdir(parents=True)
    evidence = existing / "evidence.txt"
    evidence.write_text("保留原始证据", encoding="utf-8")
    with pytest.raises(FileExistsError):
        prepare(tmp_path)
    assert evidence.read_text(encoding="utf-8") == "保留原始证据"


def test_prepare_checks_source_drift_before_generating_files(tmp_path: Path) -> None:
    previous = tmp_path / EXPERIMENT / "round-01"
    previous.mkdir(parents=True)
    source = tmp_path / "source.txt"
    source.write_text("已经漂移", encoding="utf-8")
    (previous / "freeze.json").write_text(json.dumps({"files": [
        {"path": "source.txt", "size_bytes": source.stat().st_size, "sha256": "0" * 64}
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="冻结文件漂移"):
        prepare(tmp_path)
    assert not (tmp_path / EXPERIMENT / "round-02").exists()
    assert not (tmp_path / "artifacts").exists()


def test_prepared_dispatch_contains_complete_schema_and_only_its_input() -> None:
    root = Path(__file__).resolve().parents[2]
    round_dir = root / EXPERIMENT / "round-02"
    schema = (root / "schemas/software-exploration-report.schema.json").read_text(encoding="utf-8")
    for run_id, name in (("s2-a", "s2-a-verified-requirements.json"),
                         ("s2-b", "s2-b-s1-baseline.json")):
        packet = (round_dir / "dispatch" / f"{run_id}.md").read_text(encoding="utf-8")
        assert schema in packet
        assert (round_dir / "inputs" / name).read_text(encoding="utf-8") in packet
        assert "confidence 必须是 0～1" in packet
        assert "UNREACHABLE" in packet and "PARTIALLY_MAPPED" in packet
        for private in ("ground-truth", "adjudication-decisions", "final-evaluation.md",
                        "36/46", "43/46", "62105e53", str(root)):
            assert private not in packet
