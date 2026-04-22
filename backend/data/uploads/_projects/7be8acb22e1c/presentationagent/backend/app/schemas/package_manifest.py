"""PluginPackageManifest — 声明式插件 / Skill / 主题包契约。"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PackageKind = Literal["foundation", "workflow", "skill", "theme", "tool_adapter"]
PermissionName = Literal[
    "asset.read",
    "asset.write",
    "document.parse",
    "model.invoke",
    "pptx.render",
    "preview.render",
    "registry.read",
    "settings.write",
    "web.fetch",
]

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_PACKAGE_ID_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")


class PackagePermission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: PermissionName
    rationale: str = Field(..., min_length=5)


class PackageDependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_id: str
    version_constraint: str = Field(default=">=0.0.0")
    optional: bool = False

    @field_validator("package_id")
    @classmethod
    def validate_package_id(cls, value: str) -> str:
        if not _PACKAGE_ID_RE.fullmatch(value):
            raise ValueError("package_id 格式非法")
        return value


class PackageEntrypoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["workflow", "skill_set", "theme_bundle", "adapter"]
    target: str = Field(..., min_length=2)
    description: str = Field(..., min_length=5)


class PackageCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_platform_version: str
    target_artifact_mode: list[Literal["native_pptx_first", "dual_render"]] = Field(default_factory=list)

    @field_validator("min_platform_version")
    @classmethod
    def validate_platform_version(cls, value: str) -> str:
        if not _SEMVER_RE.fullmatch(value):
            raise ValueError("min_platform_version 必须是 semver")
        return value


class PluginPackageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    package_id: str
    display_name: str = Field(..., min_length=2)
    kind: PackageKind
    version: str
    description: str = Field(..., min_length=10)
    publisher: str = Field(..., min_length=2)
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    permissions: list[PackagePermission] = Field(default_factory=list)
    dependencies: list[PackageDependency] = Field(default_factory=list)
    compatibility: PackageCompatibility
    entrypoints: list[PackageEntrypoint] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("package_id")
    @classmethod
    def validate_package_id(cls, value: str) -> str:
        if not _PACKAGE_ID_RE.fullmatch(value):
            raise ValueError("package_id 格式非法")
        return value

    @field_validator("version", "schema_version")
    @classmethod
    def validate_semver(cls, value: str) -> str:
        if not _SEMVER_RE.fullmatch(value):
            raise ValueError("版本号必须是 semver")
        return value