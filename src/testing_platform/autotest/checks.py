"""Deterministic benchmark checks against ground truth (database snapshot, config, answer)."""

from __future__ import annotations

import re
import unicodedata
from configparser import ConfigParser

from .apps.keepassxc import DbSnapshot

CHINESE_NUMBERS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
                   "八": 8, "九": 9, "十": 10}


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").strip().lower()


def numbers_in(text: str) -> set[int]:
    text = _norm(text)
    found = {int(n) for n in re.findall(r"\d+", text)}
    found |= {v for k, v in CHINESE_NUMBERS.items() if re.search(f"{k}\\s*[个条项]", text)}
    return found


def check_one(check: dict, snap: DbSnapshot | None, config: ConfigParser | None, answer: str) -> dict:
    kind = check["type"]
    ok, detail = False, ""
    if kind == "answer_number":
        nums = numbers_in(answer)
        # The expected count must appear and no competing small count (years etc. are ignored).
        ok = check["value"] in nums and all(n == check["value"] or n > 100 for n in nums)
        detail = f"numbers in answer: {sorted(nums)}"
    elif kind == "answer_text":
        ok = _norm(check["value"]) in _norm(answer)
        detail = f"answer={answer!r}"
    elif kind == "config":
        if config is None:
            return {"type": kind, "ok": False, "detail": "config unavailable"}
        section = check["section"]
        actual = {k: (config.get(section, k, fallback=None)) for k in check["values"]}
        ok = all(actual[k] is not None and _norm(actual[k]) == _norm(v) for k, v in check["values"].items())
        detail = f"{section}: {actual}"
    else:
        if snap is None:
            return {"type": kind, "ok": False, "detail": "database snapshot unavailable"}
        if kind == "entry_fields":
            entry = snap.entries.get(check["path"])
            if entry is None:
                detail = f"{check['path']} not found"
            else:
                actual = {k: entry.get(k) for k in check["fields"]}
                ok = actual == check["fields"]
                detail = f"{check['path']}: " + ", ".join(
                    f"{k}={'<match>' if actual[k] == v else repr(actual[k])}" for k, v in check["fields"].items())
        elif kind == "entry_contains":
            entry = snap.entries.get(check["path"])
            value = (entry or {}).get(check["field"], "")
            ok = entry is not None and _norm(check["value"]) in _norm(value)
            detail = f"{check['path']}.{check['field']}={value!r}" if entry else f"{check['path']} not found"
        elif kind == "entry_absent":
            paths = snap.find_title(check["title"])
            ok = not paths
            detail = f"still present at {paths}" if paths else "absent"
        elif kind == "entry_path_absent":
            ok = check["path"] not in snap.entries
            detail = "absent" if ok else "still present"
        elif kind == "group_exists":
            ok = check["path"] in snap.groups
            detail = f"groups={sorted(snap.groups)}"
        elif kind == "password_length":
            entry = snap.entries.get(check["path"])
            length = len((entry or {}).get("Password", ""))
            ok = entry is not None and length == check["length"]
            detail = f"length={length}" if entry else f"{check['path']} not found"
        else:
            raise ValueError(f"unknown check type {kind}")
    return {"type": kind, "ok": ok, "detail": detail}


def collateral_changes(seed: DbSnapshot, snap: DbSnapshot, touches: list[str]) -> list[str]:
    """Seed entries/groups outside `touches` that were changed, moved or removed."""
    out = []
    for path, fields in seed.entries.items():
        if path in touches:
            continue
        now = snap.entries.get(path)
        if now is None:
            out.append(f"entry missing: {path}")
        else:
            changed = [k for k in set(fields) | set(now) if fields.get(k, "") != now.get(k, "")]
            if changed:
                out.append(f"entry changed: {path} ({', '.join(sorted(changed))})")
    for group in seed.groups - snap.groups:
        out.append(f"group missing: {group}")
    return out


def evaluate(task: dict, snap: DbSnapshot | None, seed: DbSnapshot | None,
             config: ConfigParser | None, answer: str) -> dict:
    results = [check_one(c, snap, config, answer) for c in task["checks"]]
    collateral = collateral_changes(seed, snap, task.get("touches", [])) if snap and seed else []
    return {
        "passed": all(r["ok"] for r in results) and not collateral,
        "checks": results,
        "collateral": collateral,
    }
