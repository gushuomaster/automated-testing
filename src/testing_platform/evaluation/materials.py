from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from testing_platform.domain.documents import StrictModel, digest


class Material(StrictModel):
    id: str
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    role: Literal["construction", "calibration", "development", "regression", "formal"]
    allowed_in_formal_score: bool
    purpose: str


class MaterialRoles(StrictModel):
    schema_version: Literal["material-roles/v1"]
    materials: list[Material]
    formal_material: str | None
    formal_status: str

    @model_validator(mode="after")
    def validate_roles(self):
        if len({item.id for item in self.materials}) != len(self.materials):
            raise ValueError("材料编号不能重复")
        for item in self.materials:
            if item.allowed_in_formal_score != (item.role == "formal"):
                raise ValueError("只有 formal 材料可进入正式成绩")
        if self.formal_material and self.formal_material not in {item.id for item in self.materials if item.role == "formal"}:
            raise ValueError("正式材料未登记或角色错误")
        return self


def verify_materials(manifest: MaterialRoles, repository_root: Path) -> dict[str, str]:
    verified = {}
    for item in manifest.materials:
        path = (repository_root / item.path).resolve(strict=True)
        if digest(path.read_bytes()) != item.sha256:
            raise ValueError(f"材料哈希漂移：{item.id}")
        verified[item.id] = str(path)
    return verified
