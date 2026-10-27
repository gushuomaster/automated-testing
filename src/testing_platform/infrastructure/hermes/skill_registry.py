from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from testing_platform.paths import CONFIG_DIR

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?}")


def _expand_environment(value: str) -> str:
    return os.path.expanduser(_ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value))


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    name: str
    path: Path
    owner: str = "project"
    description: str = ""
    version: str = ""


class SkillRegistry:
    def __init__(self, definitions: dict[str, SkillDefinition]) -> None:
        self._definitions = definitions

    @classmethod
    def from_file(cls, config_path: str | Path) -> "SkillRegistry":
        path = Path(config_path).expanduser().resolve(strict=True)
        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        definitions = {}
        for name, item in (raw.get("skills") or {}).items():
            item = {"path": item} if isinstance(item, str) else item
            if not isinstance(item, dict) or not item.get("path"):
                continue
            expanded = Path(_expand_environment(str(item["path"])))
            skill_path = (expanded if expanded.is_absolute() else path.parent / expanded).resolve()
            if not (skill_path / "SKILL.md").is_file():
                raise FileNotFoundError(f"Skill 入口不存在：{skill_path / 'SKILL.md'}")
            definitions[str(name)] = SkillDefinition(str(name), skill_path, str(item.get("owner", "project")),
                                                     str(item.get("description", "")), str(item.get("version", "")))
        return cls(definitions)

    def resolve(self, identifier: str) -> SkillDefinition:
        try:
            return self._definitions[identifier]
        except KeyError as exc:
            raise LookupError(f"未注册 Skill：{identifier}") from exc

    def definitions(self) -> tuple[SkillDefinition, ...]:
        return tuple(self._definitions.values())


def resolve_skill(identifier: str, config_path: str | Path | None = None) -> SkillDefinition:
    return SkillRegistry.from_file(config_path or CONFIG_DIR / "skills.yaml").resolve(identifier.strip())
