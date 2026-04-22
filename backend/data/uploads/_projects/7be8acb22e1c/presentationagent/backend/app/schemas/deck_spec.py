"""DeckSpec — Native PPTX-first 的统一演示文稿结构契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ArtifactMode = Literal["native_pptx_first", "dual_render"]
NodeKind = Literal["text", "image", "chart", "table", "shape", "group"]


class SlideBBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(..., ge=0)
    y: float = Field(..., ge=0)
    w: float = Field(..., gt=0)
    h: float = Field(..., gt=0)


class ThemePalette(BaseModel):
    model_config = ConfigDict(extra="forbid")

    background: str
    foreground: str
    accent: str
    muted: str


class ThemeTypography(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading_font: str
    body_font: str
    mono_font: str | None = None


class ThemeSpacing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_unit: int = Field(..., ge=1)
    section_gap: int = Field(..., ge=0)
    item_gap: int = Field(..., ge=0)


class ThemeTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_id: str
    palette: ThemePalette
    typography: ThemeTypography
    spacing: ThemeSpacing
    custom: dict[str, Any] = Field(default_factory=dict)


class AssetBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    role: str
    source_type: Literal["upload", "gallery", "generated", "external"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class SlideNodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    kind: NodeKind
    role: str
    bbox: SlideBBox
    content: dict[str, Any] = Field(default_factory=dict)
    style: dict[str, Any] = Field(default_factory=dict)
    children: list["SlideNodeSpec"] = Field(default_factory=list)


class SlideSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: str
    title: str
    page_type: str
    layout_id: str
    notes: str = ""
    nodes: list[SlideNodeSpec] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SlideSize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    unit: Literal["px", "pt", "emu"] = "px"


class DeckSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deck_id: str
    schema_version: str = "1.0.0"
    revision: int = Field(default=1, ge=1)
    artifact_mode: ArtifactMode = "dual_render"
    title: str
    subtitle: str | None = None
    theme: ThemeTokens
    slide_size: SlideSize
    slides: list[SlideSpec] = Field(default_factory=list)
    source_assets: list[AssetBinding] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "DeckSpec":
        slide_ids: set[str] = set()
        node_ids: set[str] = set()

        def visit(node: SlideNodeSpec) -> None:
            if node.node_id in node_ids:
                raise ValueError(f"重复的 node_id: {node.node_id}")
            node_ids.add(node.node_id)
            for child in node.children:
                visit(child)

        for slide in self.slides:
            if slide.slide_id in slide_ids:
                raise ValueError(f"重复的 slide_id: {slide.slide_id}")
            slide_ids.add(slide.slide_id)
            for node in slide.nodes:
                visit(node)

        return self


SlideNodeSpec.model_rebuild()