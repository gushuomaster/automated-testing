from __future__ import annotations

import argparse
import json
from pathlib import Path


def find_report(session_log: Path, run_id: str) -> str:
    matches: list[str] = []
    for line in session_log.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        payload = record.get("payload", {})
        if record.get("type") != "event_msg" or payload.get("type") != "task_complete":
            continue
        message = payload.get("last_agent_message")
        if not isinstance(message, str):
            continue
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError:
            continue
        if parsed.get("schema_version") == "software-exploration-report/v1" and parsed.get("run_id") == run_id:
            matches.append(message)
    if len(matches) != 1:
        raise ValueError(f"期望唯一的 {run_id} 原始报告，实际找到 {len(matches)} 个")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="从本地 Codex 会话日志提取并原样保存 S2 Agent 报告")
    parser.add_argument("--session-log", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = find_report(args.session_log, args.run_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report + ("" if report.endswith("\n") else "\n"), encoding="utf-8", newline="\n")
    print(args.output)


if __name__ == "__main__":
    main()
