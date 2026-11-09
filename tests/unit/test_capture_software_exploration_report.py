from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "capture_software_exploration_report", ROOT / "scripts/capture_software_exploration_report.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_find_report_selects_unique_matching_run(tmp_path: Path) -> None:
    expected = json.dumps({"schema_version": "software-exploration-report/v1", "run_id": "s2-a"}, ensure_ascii=False)
    records = [
        {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "not json"}},
        {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": expected}},
    ]
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records), encoding="utf-8")
    assert MODULE.find_report(path, "s2-a") == expected
