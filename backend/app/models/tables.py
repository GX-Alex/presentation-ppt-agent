"""
数据库表定义 —— 对齐需求文档 V3.1 §8。
所有表使用 UUID 主键，包含 user_id 为后续多租户预留。
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.sqlite import JSON  # portable JSON type
from sqlalchemy.orm import relationship

from app.models.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────── 用户表 ───────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=True)
    name = Column(String(127), nullable=True)
    avatar_url = Column(String(1024), nullable=True)
    settings = Column(JSON, nullable=True)  # 主题、默认模型、记忆开关
    created_at = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────────── 任务表 ───────────────────────────────

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=True)
    status = Column(String(20), default="active")  # active | completed | archived (状态)
    intent = Column(String(30), nullable=True)  # ppt | research | code_analysis | chat (意图)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("TaskMessage", back_populates="task", cascade="all, delete-orphan")
    checkpoints = relationship("TaskCheckpoint", back_populates="task", cascade="all, delete-orphan")


# ─────────────────────────── 任务消息表 ───────────────────────────

class TaskMessage(Base):
    __tablename__ = "task_messages"

    id = Column(String(36), primary_key=True, default=_uuid)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    role = Column(String(20), nullable=False)  # user | assistant | system | tool (角色)
    content = Column(Text, nullable=True)  # 消息内容
    msg_type = Column(String(30), nullable=True)  # text | thinking | plan | slide | ... (消息类型)
    tool_name = Column(String(63), nullable=True)  # 工具名称
    tool_input = Column(JSON, nullable=True)  # 工具输入参数
    reasoning_content = Column(Text, nullable=True)  # DeepSeek reasoning models: thinking chain
    is_compressed = Column(Boolean, default=False)  # 是否已压缩
    token_count = Column(Integer, nullable=True)  # Token 用量
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", back_populates="messages")


# ───────────────────────────── 检查点表 ─────────────────────────────

class TaskCheckpoint(Base):
    __tablename__ = "task_checkpoints"

    id = Column(String(36), primary_key=True, default=_uuid)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    step_index = Column(Integer, nullable=False)
    state = Column(JSON, nullable=False)  # Agent 状态快照
    summary = Column(Text, nullable=True)  # 摘要
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("task_id", "step_index"),)

    task = relationship("Task", back_populates="checkpoints")


# ──────────────────────────────── 资产表 ────────────────────────────────

class Asset(Base):
    __tablename__ = "assets"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    file_type = Column(String(30), nullable=False)  # document | ppt | code | image | skill (文件类型)
    source = Column(String(30), nullable=False)  # upload | ai_generated | remix (来源)
    mime_type = Column(String(127), nullable=True)
    file_url = Column(String(1024), nullable=True)
    thumbnail_url = Column(String(1024), nullable=True)
    file_size = Column(Integer, nullable=True)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=True)
    parent_id = Column(String(36), ForeignKey("assets.id"), nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ────────────────────────────── 画廊项目表 ──────────────────────────────

class GalleryItem(Base):
    __tablename__ = "gallery_items"

    id = Column(String(36), primary_key=True, default=_uuid)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False)
    author_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    category = Column(String(30), nullable=False)  # ppt | research | code | skill | other
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    preview_url = Column(String(1024), nullable=True)
    is_featured = Column(Boolean, default=False)
    remix_count = Column(Integer, default=0)
    view_count = Column(Integer, default=0)
    version = Column(Integer, default=1)
    license = Column(String(30), default="cc-by-4.0")
    published_at = Column(DateTime, default=datetime.utcnow)


# ──────────────────────────── User Skills ────────────────────────────

class UserSkill(Base):
    __tablename__ = "user_skills"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    name = Column(String(63), nullable=False)
    display_name = Column(String(127), nullable=True)
    description = Column(Text, nullable=False)
    tags = Column(Text, nullable=True)  # 逗号分隔的标签
    body = Column(Text, nullable=False)  # 完整 Markdown 内容
    required_tools = Column(Text, nullable=True)  # 依赖的工具
    status = Column(String(20), default="draft")  # draft | validated | published (状态)
    is_enabled = Column(Boolean, default=False)  # 是否启用
    is_public = Column(Boolean, default=False)  # 是否公开
    scope = Column(String(20), default="manual")  # manual | auto (范围)
    validation_result = Column(JSON, nullable=True)
    validated_at = Column(DateTime, nullable=True)
    usage_count = Column(Integer, default=0)
    fork_count = Column(Integer, default=0)
    source_skill_id = Column(String(36), nullable=True)
    gallery_version = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "name"),)


# ─────────────────────────── Installed Packages ───────────────────────────

class InstalledPackage(Base):
    __tablename__ = "installed_packages"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    package_id = Column(String(127), nullable=False)
    display_name = Column(String(255), nullable=False)
    package_kind = Column(String(30), nullable=False)  # foundation | workflow | skill | theme | tool_adapter
    version = Column(String(30), nullable=False)
    source = Column(String(30), default="registry")  # registry | local | imported
    manifest = Column(JSON, nullable=False)
    granted_permissions = Column(JSON, nullable=False)
    status = Column(String(20), default="installed")  # installed | upgraded | disabled
    is_enabled = Column(Boolean, default=True)
    installed_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "package_id"),)


# ─────────────────────────── P2 Plugin Platform ───────────────────────────

class PluginPackage(Base):
    __tablename__ = "plugin_packages"

    id = Column(String(36), primary_key=True, default=_uuid)
    package_id = Column(String(127), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    package_kind = Column(String(30), nullable=False)  # foundation | workflow | skill | theme | tool_adapter
    description = Column(Text, nullable=False)
    publisher = Column(String(127), nullable=False)
    tags = Column(JSON, nullable=False, default=list)
    source = Column(String(30), default="builtin")  # builtin | imported | registry | local
    source_ref = Column(String(255), nullable=True)
    latest_version = Column(String(30), nullable=True)
    is_public = Column(Boolean, default=True)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PluginVersion(Base):
    __tablename__ = "plugin_versions"

    id = Column(String(36), primary_key=True, default=_uuid)
    plugin_package_id = Column(String(36), ForeignKey("plugin_packages.id"), nullable=False)
    package_id = Column(String(127), nullable=False)
    version = Column(String(30), nullable=False)
    manifest = Column(JSON, nullable=False)
    capabilities = Column(JSON, nullable=False, default=list)
    permissions = Column(JSON, nullable=False, default=list)
    dependencies = Column(JSON, nullable=False, default=list)
    entrypoints = Column(JSON, nullable=False, default=list)
    resource_manifest = Column(JSON, nullable=True)
    release_notes = Column(Text, nullable=True)
    upgrade_notes = Column(Text, nullable=True)
    integrity_hash = Column(String(127), nullable=True)
    is_imported = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("package_id", "version"),)


class InstalledPlugin(Base):
    __tablename__ = "installed_plugins"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    plugin_package_id = Column(String(36), ForeignKey("plugin_packages.id"), nullable=False)
    active_version_id = Column(String(36), ForeignKey("plugin_versions.id"), nullable=False)
    package_id = Column(String(127), nullable=False)
    display_name = Column(String(255), nullable=False)
    package_kind = Column(String(30), nullable=False)
    version = Column(String(30), nullable=False)
    source = Column(String(30), default="registry")
    manifest_snapshot = Column(JSON, nullable=False)
    granted_permissions = Column(JSON, nullable=False)
    installed_history = Column(JSON, nullable=False, default=list)
    status = Column(String(20), default="installed")  # installed | upgraded | rolled_back | disabled
    is_enabled = Column(Boolean, default=True)
    metadata_ = Column("metadata", JSON, nullable=True)
    installed_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "package_id"),)


class WorkflowBinding(Base):
    __tablename__ = "workflow_bindings"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    installed_plugin_id = Column(String(36), ForeignKey("installed_plugins.id"), nullable=False)
    package_id = Column(String(127), nullable=False)
    binding_key = Column(String(255), nullable=False)
    binding_type = Column(String(30), default="presentation")  # presentation | task | default | asset
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=True)
    presentation_id = Column(String(36), ForeignKey("presentations.id"), nullable=True)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=True)
    config = Column(JSON, nullable=True)
    is_enabled = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "binding_key"),)


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    installed_plugin_id = Column(String(36), ForeignKey("installed_plugins.id"), nullable=True)
    plugin_version_id = Column(String(36), ForeignKey("plugin_versions.id"), nullable=True)
    package_id = Column(String(127), nullable=False)
    package_version = Column(String(30), nullable=True)
    execution_kind = Column(String(30), nullable=False)  # import | install | upgrade | rollback | workflow | render | export
    target_type = Column(String(30), nullable=True)  # package | presentation | task | asset
    target_id = Column(String(127), nullable=True)
    status = Column(String(20), default="succeeded")  # running | succeeded | failed
    input_payload = Column(JSON, nullable=True)
    output_payload = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class ArtifactVariant(Base):
    __tablename__ = "artifact_variants"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    variant_key = Column(String(255), nullable=False)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=True)
    presentation_id = Column(String(36), ForeignKey("presentations.id"), nullable=True)
    installed_plugin_id = Column(String(36), ForeignKey("installed_plugins.id"), nullable=True)
    execution_log_id = Column(String(36), ForeignKey("execution_logs.id"), nullable=True)
    package_id = Column(String(127), nullable=False)
    package_version = Column(String(30), nullable=True)
    variant_type = Column(String(30), nullable=False)  # html-preview | pdf | thumbnail | legacy values
    mime_type = Column(String(127), nullable=True)
    file_url = Column(String(1024), nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "variant_key"),)


# ──────────────────────────── User Memories ──────────────────────────

class UserMemory(Base):
    __tablename__ = "user_memories"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    category = Column(String(30), nullable=False)  # preference | fact | instruction | feedback (类型)
    content = Column(Text, nullable=False)  # 记忆内容
    embedding = Column(Text, nullable=True)  # JSON 序列化向量，后续迁移 to pgvector
    source = Column(String(30), nullable=True)  # auto_captured | user_explicit | agent_inferred (来源)
    source_task_id = Column(String(36), nullable=True)
    confidence = Column(Float, default=1.0)
    supersedes = Column(String(36), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─────────────────────────── Document Chunks ─────────────────────────

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String(36), primary_key=True, default=_uuid)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Text, nullable=True)  # JSON 序列化向量
    metadata_ = Column("metadata", JSON, nullable=True)  # {page_num, heading, file_name} (元数据)
    created_at = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────── Presentations ───────────────────────────

class Presentation(Base):
    __tablename__ = "presentations"

    id = Column(String(36), primary_key=True, default=_uuid)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    title = Column(String(255), nullable=True)
    theme = Column(JSON, nullable=False)
    outline = Column(JSON, nullable=True)
    source_docs = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    slides = relationship("Slide", back_populates="presentation", cascade="all, delete-orphan")


# ──────────────────────────────── Slides ─────────────────────────────

class Slide(Base):
    __tablename__ = "slides"

    id = Column(String(36), primary_key=True, default=_uuid)
    presentation_id = Column(String(36), ForeignKey("presentations.id"), nullable=False)
    index = Column(Integer, nullable=False)
    type = Column(String(30), nullable=True)  # title | content | two-column | ... (幻灯片类型)
    html = Column(Text, nullable=False)  # 幻灯片 HTML 内容
    speaker_notes = Column(Text, nullable=True)  # 演讲者备注
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    presentation = relationship("Presentation", back_populates="slides")
    versions = relationship("SlideVersion", back_populates="slide", cascade="all, delete-orphan")


class SlideVersion(Base):
    __tablename__ = "slide_versions"

    id = Column(String(36), primary_key=True, default=_uuid)
    slide_id = Column(String(36), ForeignKey("slides.id"), nullable=False)
    version = Column(Integer, nullable=False)
    html = Column(Text, nullable=False)  # 版本快照 HTML
    source = Column(String(20), nullable=True)  # wysiwyg | ai | fork (修改来源)
    created_at = Column(DateTime, default=datetime.utcnow)

    slide = relationship("Slide", back_populates="versions")


# ─────────────────────────── Web Deck Runtime ───────────────────────────

class DeckProject(Base):
    __tablename__ = "deck_projects"

    id = Column(String(36), primary_key=True, default=_uuid)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=True)
    subtitle = Column(String(255), nullable=True)
    status = Column(String(30), default="draft")
    version = Column(Integer, default=1)
    brief = Column(JSON, nullable=True)
    manifest = Column(JSON, nullable=True)
    global_theme = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DeckVersion(Base):
    __tablename__ = "deck_versions"

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("deck_projects.id"), nullable=False)
    version = Column(Integer, nullable=False)
    manifest_snapshot = Column(JSON, nullable=False)
    change_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "version"),)


class DeckPage(Base):
    __tablename__ = "deck_pages"

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("deck_projects.id"), nullable=False)
    page_id = Column(String(127), nullable=False)
    page_index = Column(Integer, nullable=False)
    title = Column(String(255), nullable=True)
    page_kind = Column(String(30), nullable=True)
    status = Column(String(30), default="pending")
    page_spec = Column(JSON, nullable=True)
    page_bundle = Column(JSON, nullable=True)
    html = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "page_id"),)


class DeckPageVersion(Base):
    __tablename__ = "deck_page_versions"

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("deck_projects.id"), nullable=False)
    page_db_id = Column(String(36), ForeignKey("deck_pages.id"), nullable=False)
    version = Column(Integer, nullable=False)
    source = Column(String(20), nullable=False, default="manual")
    html = Column(Text, nullable=False)
    change_summary = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("page_db_id", "version"),)


class LaneRun(Base):
    __tablename__ = "deck_lane_runs"

    id = Column(String(36), primary_key=True, default=_uuid)
    page_id = Column(String(36), ForeignKey("deck_pages.id"), nullable=False)
    project_id = Column(String(36), ForeignKey("deck_projects.id"), nullable=False)
    lane_id = Column(String(127), nullable=False)
    kind = Column(String(30), nullable=False)
    status = Column(String(30), default="pending")
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    retries = Column(Integer, default=0)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "lane_id"),)


class DeckAssetNode(Base):
    __tablename__ = "deck_asset_nodes"

    id = Column(String(36), primary_key=True, default=_uuid)
    page_id = Column(String(36), ForeignKey("deck_pages.id"), nullable=False)
    project_id = Column(String(36), ForeignKey("deck_projects.id"), nullable=False)
    asset_id = Column(String(127), nullable=False)
    kind = Column(String(30), nullable=False)
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "asset_id"),)


class DeckReviewReport(Base):
    __tablename__ = "deck_review_reports"

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("deck_projects.id"), nullable=False)
    page_id = Column(String(36), ForeignKey("deck_pages.id"), nullable=True)
    level = Column(String(20), nullable=False)
    passed = Column(Boolean, default=False)
    score = Column(Float, default=0.0)
    issues = Column(JSON, nullable=True)
    suggestions = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DeckPublish(Base):
    __tablename__ = "deck_publishes"

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("deck_projects.id"), nullable=False)
    version = Column(Integer, nullable=False)
    full_html = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "version"),)
