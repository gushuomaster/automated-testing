from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any


EXPECTED_EXE_SHA256 = "62105e53aa16b042bc86168f4d420d9fc4ccd012b75cf27f7048786c79534b15"
EXPECTED_REQUIREMENTS_SHA256 = "033bee6c01fe24ddae53d449b309f44b470a864cdd4583bb4bd7b17b4fdc603f"

NOT_UI_OBSERVABLE = {"REQ-004", "REQ-045", "REQ-049", "REQ-050", "REQ-051", "REQ-052"}
DIRECTLY_MAPPED = {
    "REQ-001", "REQ-002", "REQ-003", "REQ-005", "REQ-006", "REQ-007", "REQ-008", "REQ-009",
    "REQ-020", "REQ-021", "REQ-022", "REQ-036", "REQ-037", "REQ-038", "REQ-039", "REQ-040",
    "REQ-041", "REQ-042", "REQ-043",
}

CONTROL_GROUPS = {
    "window": ["MiniOrder 主窗口"],
    "create_page": ["新建订单"],
    "query_page": ["查询订单"],
    "customer": ["客户名称"],
    "product": ["商品名称"],
    "quantity": ["数量"],
    "unit_price": ["单价"],
    "amount": ["订单金额"],
    "save": ["保存订单", "订单录入状态"],
    "query": ["查询关键字", "订单状态筛选", "查询", "订单查询结果", "查询结果数量"],
    "clear_filters": ["清除筛选", "订单查询结果", "查询结果数量"],
    "grid": ["订单查询结果", "订单编号", "客户名称", "商品名称", "数量", "单价", "订单金额", "状态", "创建时间"],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def evidence_profile(requirement_id: str) -> tuple[str, list[str], str]:
    number = int(requirement_id.split("-")[1])
    if requirement_id == "REQ-001":
        return "window", CONTROL_GROUPS["window"], "startup"
    if requirement_id == "REQ-002":
        return "create_order", CONTROL_GROUPS["create_page"], "startup > 新建订单"
    if requirement_id == "REQ-003":
        return "query_order", CONTROL_GROUPS["query_page"], "startup > 查询订单"
    if requirement_id in NOT_UI_OBSERVABLE:
        return "non_gui", [], "not available through the public GUI"
    if requirement_id in {"REQ-005", "REQ-010", "REQ-011"}:
        return "create_order", CONTROL_GROUPS["customer"], "startup > 新建订单"
    if requirement_id in {"REQ-006", "REQ-012", "REQ-013"}:
        return "create_order", CONTROL_GROUPS["product"], "startup > 新建订单"
    if requirement_id in {"REQ-007", "REQ-014", "REQ-015", "REQ-016"}:
        return "create_order", CONTROL_GROUPS["quantity"], "startup > 新建订单"
    if requirement_id in {"REQ-008", "REQ-017", "REQ-018", "REQ-019"}:
        return "create_order", CONTROL_GROUPS["unit_price"], "startup > 新建订单"
    if requirement_id in {"REQ-009", "REQ-020", "REQ-021", "REQ-022", "REQ-023", "REQ-024"}:
        controls = CONTROL_GROUPS["amount"] if requirement_id not in {"REQ-021", "REQ-023", "REQ-024"} else (
            CONTROL_GROUPS["quantity"] + CONTROL_GROUPS["unit_price"] + CONTROL_GROUPS["amount"]
        )
        return "create_order", controls, "startup > 新建订单"
    if 25 <= number <= 35:
        return "create_order", CONTROL_GROUPS["save"], "startup > 新建订单 > 保存订单"
    if requirement_id == "REQ-040":
        return "query_order", CONTROL_GROUPS["clear_filters"], "startup > 查询订单 > 清除筛选"
    if requirement_id in {"REQ-036", "REQ-043", "REQ-044"}:
        return "query_order", CONTROL_GROUPS["grid"], "startup > 查询订单"
    if 37 <= number <= 42:
        return "query_order", CONTROL_GROUPS["query"], "startup > 查询订单 > 查询"
    if 46 <= number <= 48:
        return "runtime_boundary", CONTROL_GROUPS["query_page"] + CONTROL_GROUPS["grid"], "restart/data-directory setup > 查询订单"
    raise ValueError(f"未分类的需求：{requirement_id}")


def expected_status(requirement_id: str) -> str:
    if requirement_id in NOT_UI_OBSERVABLE:
        return "NOT_UI_OBSERVABLE"
    if requirement_id in DIRECTLY_MAPPED:
        return "MAPPED"
    return "PARTIALLY_MAPPED"


def build_assets(root: Path) -> dict[str, Path]:
    baseline_path = root / "artifacts/requirement-analysis/preruns/calibration/3960ded9-e5fc-4079-a214-d9ee43e4a74f/artifacts/10d57fe2-6b9a-49de-929a-ffb6988d28e1/requirement-baseline-initial.json"
    requirements_path = root / "docs/miniorder/MiniOrder-Requirements.md"
    exe_path = root / "artifacts/miniorder/blackbox-run/MiniOrder.exe"
    seed_path = root / "samples/MiniOrder/evaluation/seed/orders.json"
    protocol_path = root / "evaluation/software-exploration/experiments/round-01/protocol.md"
    prompt_path = root / "evaluation/software-exploration/experiments/round-01/test-agent-prompt.md"
    schema_path = root / "schemas/software-exploration-report.schema.json"

    if sha256(exe_path) != EXPECTED_EXE_SHA256:
        raise ValueError("MiniOrder Baseline EXE 哈希漂移")
    if sha256(requirements_path) != EXPECTED_REQUIREMENTS_SHA256:
        raise ValueError("MiniOrder 中文需求哈希漂移")

    baseline = read_json(baseline_path)
    requirements = baseline["parsed"]["requirements"]
    ambiguities = baseline["parsed"]["ambiguities"]
    if [item["id"] for item in requirements] != [f"REQ-{index:03d}" for index in range(1, 53)]:
        raise ValueError("S1 MiniOrder 基线需求编号或数量漂移")

    experiment = root / "evaluation/software-exploration/experiments/round-01"
    input_dir = experiment / "inputs"
    truth_path = root / "evaluation/software-exploration/ground-truth/miniorder-v1.json"
    input_a_path = input_dir / "s2-a-verified-requirements.json"
    input_b_path = input_dir / "s2-b-s1-baseline.json"
    environment_path = experiment / "environment.json"
    freeze_path = experiment / "freeze.json"

    input_a = {
        "schema_version": "software-exploration-input/v1",
        "input_role": "verified-upstream",
        "subject": "匿名 Windows 订单管理软件",
        "requirements": [
            {
                "id": item["id"],
                "description": item["description"],
                "expected_behavior": item["expected_behavior"],
                "source_segment_ids": baseline["parsed"]["trace_index"][item["id"]],
            }
            for item in requirements
        ],
        "ambiguities": [
            {"id": item["id"], "description": item["description"], "impact": item["impact"], "requirement_ids": item["requirement_ids"]}
            for item in ambiguities
        ],
    }
    input_b = {
        "schema_version": "software-exploration-input/v1",
        "input_role": "s1-actual-output",
        "subject": "匿名 Windows 订单管理软件",
        "source_baseline_sha256": sha256(baseline_path),
        "requirements": [
            {
                key: item[key]
                for key in ("id", "target", "categories", "description", "conditions", "expected_behavior", "information_nature", "confidence", "verification_status")
            }
            | {"source_segment_ids": baseline["parsed"]["trace_index"][item["id"]]}
            for item in requirements
        ],
        "ambiguities": [
            {"id": item["id"], "description": item["description"], "impact": item["impact"], "requirement_ids": item["requirement_ids"]}
            for item in ambiguities
        ],
    }

    truth_requirements = []
    for item in requirements:
        area, controls, route = evidence_profile(item["id"])
        truth_requirements.append({
            "requirement_id": item["id"],
            "expected_status": expected_status(item["id"]),
            "scored_as_ui_related": item["id"] not in NOT_UI_OBSERVABLE,
            "ui_area": area,
            "acceptable_visible_evidence": controls,
            "route_class": route,
        })
    truth = {
        "schema_version": "software-exploration-ground-truth/v1",
        "subject": "MiniOrder Baseline",
        "critical_entries": [
            {"id": "ENTRY-CREATE", "visible_name": "新建订单"},
            {"id": "ENTRY-QUERY", "visible_name": "查询订单"},
        ],
        "requirements": truth_requirements,
        "classification_counts": {
            status: sum(1 for item in truth_requirements if item["expected_status"] == status)
            for status in ("MAPPED", "PARTIALLY_MAPPED", "NOT_UI_OBSERVABLE")
        },
    }

    write_json(input_a_path, input_a)
    write_json(input_b_path, input_b)
    write_json(truth_path, truth)

    try:
        git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        git_status = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=root, text=True, encoding="utf-8").splitlines()
    except (OSError, subprocess.CalledProcessError):
        git_head, git_status = "unavailable", []

    skill_candidates = sorted((Path.home() / ".codex/plugins/cache/openai-bundled/computer-use").glob("*/skills/computer-use/SKILL.md"))
    skill_path = skill_candidates[-1] if skill_candidates else None
    environment = {
        "schema_version": "software-exploration-environment/v1",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "git_head": git_head,
        "working_tree_changes": git_status,
        "computer_use_bundle": skill_path.parents[2].name if skill_path else "unavailable",
        "computer_use_skill_sha256": sha256(skill_path) if skill_path else None,
        "uia_entry": "mcp__node_repl__js + @oai/sky",
        "pid": os.getpid(),
    }
    write_json(environment_path, environment)

    frozen_paths = [
        exe_path, requirements_path, seed_path, baseline_path, input_a_path, input_b_path, truth_path,
        protocol_path, prompt_path, schema_path, environment_path,
    ]
    freeze = {
        "schema_version": "software-exploration-freeze/v1",
        "frozen": True,
        "files": [
            {"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in frozen_paths
        ],
        "budget": {"max_minutes": 15, "max_gui_actions": 30, "max_same_action_retries": 2, "max_window_rebinds": 1},
        "thresholds": {
            "critical_entry_recall": 1.0,
            "ui_requirement_mapping_recall": 0.90,
            "mapping_precision": 0.95,
            "reproducible_path_rate": 0.95,
            "unsupported_control_rate_max": 0.05,
            "persistent_side_effects": 0,
        },
    }
    write_json(freeze_path, freeze)

    artifact_root = root / "artifacts/software-exploration/round-01"
    for run_name in ("health-check", "s2-a", "s2-b"):
        sut_dir = artifact_root / run_name / "sut"
        data_dir = artifact_root / run_name / "data"
        sut_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(exe_path, sut_dir / "MiniOrder.exe")
        shutil.copy2(seed_path, data_dir / "orders.json")

    return {
        "input_a": input_a_path,
        "input_b": input_b_path,
        "truth": truth_path,
        "environment": environment_path,
        "freeze": freeze_path,
        "artifact_root": artifact_root,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="准备 MiniOrder S2 软件探索实验资产")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = build_assets(args.root.resolve())
    print(json.dumps({key: str(value) for key, value in result.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
