"""
Skill 服务 — 系统技能加载 + 用户自定义 Skill CRUD + 验证 + 冲突策略。
Sprint 4: 两层 Skill 加载（系统预置 → 用户自定义），作用域与冲突管理。
"""
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import UserSkill

logger = logging.getLogger(__name__)

# 系统 Skill 目录
SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

# 系统预置 Skill 元数据（名称 → 文件名 + 展示名 + 标签）
SYSTEM_SKILLS: dict[str, dict[str, Any]] = {
    "pptx": {
        "file": "pptx/SKILL.md",
        "display_name": "PPTX 文档编辑专家",
        "description": "直接修改现有 .pptx 并精确控制页面、文本、样式与版式",
        "tags": "pptx,ppt,幻灯片,office,演示",
        "required_tools": "load_skill",
    },
    "docx": {
        "file": "docx/SKILL.md",
        "display_name": "DOCX 文档编辑专家",
        "description": "直接编辑 .docx 并处理批注、修订、结构化内容与文档一致性",
        "tags": "docx,word,文档,office,批注",
        "required_tools": "load_skill",
    },
    "research_analyst": {
        "file": "research_analyst.md",
        "display_name": "研究分析师",
        "description": "系统性收集、整理和分析信息，输出结构化研究报告",
        "tags": "研究,分析,报告",
        "required_tools": "web_search",
    },
    "code_reviewer": {
        "file": "code_reviewer.md",
        "display_name": "代码审查专家",
        "description": "识别Bug、安全漏洞、性能瓶颈和代码反模式",
        "tags": "代码,审查,开发",
        "required_tools": "web_search",
    },
    "data_analyst": {
        "file": "data_analyst.md",
        "display_name": "数据分析师",
        "description": "从原始数据中提炼洞见，用数据驱动决策",
        "tags": "数据,分析,统计",
        "required_tools": "web_search,parse_document",
    },
    "writing_coach": {
        "file": "writing_coach.md",
        "display_name": "写作教练",
        "description": "精通各类文体写作技巧，帮助提升文字表达质量",
        "tags": "写作,润色,文案",
        "required_tools": "web_search",
    },
    "meeting_facilitator": {
        "file": "meeting_facilitator.md",
        "display_name": "会议主持人",
        "description": "组织和总结会议内容，确保产出高质量行动项",
        "tags": "会议,纪要,总结",
        "required_tools": "parse_document,web_search",
    },
    # ── Anthropic 官方 Skills 集成 ──────────────────────────────────────
    "algorithmic_art": {
        "file": "algorithmic_art.md",
        "display_name": "算法生成艺术专家",
        "description": "使用 p5.js 创作概念驱动的生成艺术作品，将数学与代码转化为视觉体验",
        "tags": "艺术,生成艺术,p5js,创意编程,可视化",
        "required_tools": "web_search,fetch_url",
    },
    "canvas_design": {
        "file": "canvas_design.md",
        "display_name": "视觉设计哲学专家",
        "description": "以设计哲学为指导，创作书法、扁平插画、水彩等视觉艺术作品",
        "tags": "设计,视觉艺术,插画,创意",
        "required_tools": "web_search",
    },
    "frontend_design": {
        "file": "frontend_design.md",
        "display_name": "前端美学设计专家",
        "description": "精通排版、色彩、动效的前端 UI 设计，避免 AI 生成的同质化视觉",
        "tags": "前端,设计,CSS,排版,UI",
        "required_tools": "web_search",
    },
    "internal_comms": {
        "file": "internal_comms.md",
        "display_name": "内部沟通写作专家",
        "description": "起草清晰有力的内部通知、3P 周报、新闻简报和危机沟通文件",
        "tags": "写作,公司内部,沟通,模板,邮件",
        "required_tools": "web_search",
    },
    "mcp_builder": {
        "file": "mcp_builder.md",
        "display_name": "MCP 服务器开发专家",
        "description": "设计和实现 Model Context Protocol (MCP) 服务器，为 AI 提供工具和资源",
        "tags": "MCP,开发,工具,TypeScript,Python",
        "required_tools": "web_search,fetch_url",
    },
    "claude_api_dev": {
        "file": "claude_api_dev.md",
        "display_name": "Claude API 开发专家",
        "description": "构建基于 Claude API 的高质量应用，精通模型选择、流式输出和性能优化",
        "tags": "Claude,API,开发,AI,SDK",
        "required_tools": "web_search,fetch_url",
    },
    "docx_writer": {
        "file": "docx_writer.md",
        "display_name": "Word 文档处理专家",
        "description": "使用 python-docx 创建和编辑专业 Word 文档，处理格式、表格和多级标题",
        "tags": "Word,文档,DOCX,报告,python-docx",
        "required_tools": "parse_document,web_search",
    },
    "pdf_processor": {
        "file": "pdf_processor.md",
        "display_name": "PDF 处理专家",
        "description": "提取、分析和生成 PDF 文档，支持文本提取、OCR 和专业排版",
        "tags": "PDF,文档,提取,OCR,ReportLab",
        "required_tools": "parse_document,web_search",
    },
    "xlsx_analyst": {
        "file": "xlsx_analyst.md",
        "display_name": "Excel 数据分析专家",
        "description": "用 pandas 和 openpyxl 进行数据分析和财务建模，严格遵循公式驱动原则",
        "tags": "Excel,数据,pandas,财务,openpyxl",
        "required_tools": "parse_document,web_search",
    },
    "web_builder": {
        "file": "web_builder.md",
        "display_name": "Web 前端应用专家",
        "description": "使用 React+TypeScript+Tailwind+shadcn/ui 构建高质量单页应用，反 AI 同质化设计",
        "tags": "React,前端,TypeScript,Tailwind,Web",
        "required_tools": "web_search,fetch_url",
    },
    "webapp_tester": {
        "file": "webapp_tester.md",
        "display_name": "Web 应用测试专家",
        "description": "用 Python Playwright 编写端到端测试，验证功能、表单和认证流程",
        "tags": "测试,Playwright,自动化,E2E,Python",
        "required_tools": "web_search",
    },
    "skill_creator": {
        "file": "skill_creator.md",
        "display_name": "Skill 设计专家",
        "description": "设计和创建高质量的 AI Skill 文件，遵循捕捉意图→访谈→编写→测试迭代流程",
        "tags": "skill,设计,meta,创建,AI",
        "required_tools": "web_search,fetch_url",
    },
    "gif_animator": {
        "file": "gif_animator.md",
        "display_name": "GIF 动画创作专家",
        "description": "使用 PIL/Pillow 创建流畅的 GIF 动画，掌握缓动函数和各类动画模式",
        "tags": "GIF,动画,PIL,Python,创意",
        "required_tools": "web_search",
    },
    "brand_design": {
        "file": "brand_design.md",
        "display_name": "品牌设计专家",
        "description": "构建系统化品牌视觉体系，包括色彩规范、字体系统和设计语言",
        "tags": "品牌,设计,色彩,字体,视觉",
        "required_tools": "web_search,fetch_url",
    },
}

# 内存缓存: 已加载的系统 Skill 正文
_system_skill_cache: dict[str, str] = {}


def load_system_skills() -> None:
    """启动时加载所有系统 Skill .md 文件到内存缓存。"""
    _system_skill_cache.clear()
    for name, meta in SYSTEM_SKILLS.items():
        filepath = SKILLS_DIR / meta["file"]
        if filepath.exists():
            _system_skill_cache[name] = filepath.read_text(encoding="utf-8")
            logger.info(f"[Skill] 加载系统 Skill: {name} ({meta['display_name']})")
        else:
            logger.warning(f"[Skill] 系统 Skill 文件缺失: {filepath}")


def get_system_skill_body(name: str) -> str | None:
    """获取系统 Skill 正文（从缓存读取）。"""
    return _system_skill_cache.get(name)


def get_system_skill_list() -> list[dict[str, Any]]:
    """获取系统 Skill 列表（不含正文）。"""
    result = []
    for name, meta in SYSTEM_SKILLS.items():
        result.append({
            "name": name,
            "display_name": meta["display_name"],
            "description": meta["description"],
            "tags": meta["tags"],
            "required_tools": meta["required_tools"],
            "is_system": True,
            "is_loaded": name in _system_skill_cache,
        })
    return result


def get_skill_menu() -> str:
    """
    生成 Layer 1 Skill 菜单文本 — 注入系统提示词中，
    供 LLM 知道可用的 Skill 和何时应调用 load_skill。
    """
    lines = ["## 可用 Skill 列表", "根据用户需求，你可以调用 `load_skill` 工具加载对应的专业角色。", ""]
    for name, meta in SYSTEM_SKILLS.items():
        loaded = "✅ 已加载" if name in _system_skill_cache else ""
        lines.append(f"- **{meta['display_name']}** (`{name}`): {meta['description']} {loaded}")
    lines.append("")
    lines.append("调用方式: 使用 `load_skill` 工具，传入 skill_name 参数。")
    return "\n".join(lines)


# ──────────────── 用户自定义 Skill CRUD ────────────────


async def list_user_skills(
    session: AsyncSession,
    user_id: str,
    include_disabled: bool = True,
) -> list[dict[str, Any]]:
    """列出用户的所有自定义 Skill。"""
    stmt = select(UserSkill).where(UserSkill.user_id == user_id)
    if not include_disabled:
        stmt = stmt.where(UserSkill.is_enabled == True)  # noqa: E712
    stmt = stmt.order_by(UserSkill.updated_at.desc())
    result = await session.execute(stmt)
    skills = result.scalars().all()
    return [_skill_to_dict(s) for s in skills]


async def get_user_skill(
    session: AsyncSession,
    skill_id: str,
) -> dict[str, Any] | None:
    """获取单个 Skill 详情。"""
    result = await session.execute(
        select(UserSkill).where(UserSkill.id == skill_id)
    )
    skill = result.scalar_one_or_none()
    return _skill_to_dict(skill) if skill else None


async def create_user_skill(
    session: AsyncSession,
    user_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """创建新的用户自定义 Skill。"""
    skill = UserSkill(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=data["name"],
        display_name=data.get("display_name", data["name"]),
        description=data.get("description", ""),
        tags=data.get("tags", ""),
        body=data["body"],
        required_tools=data.get("required_tools", ""),
        status="draft",
        is_enabled=False,
        scope=data.get("scope", "manual"),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(skill)
    await session.commit()
    await session.refresh(skill)
    logger.info(f"[Skill] 创建用户 Skill: {skill.name} (id={skill.id})")
    return _skill_to_dict(skill)


async def update_user_skill(
    session: AsyncSession,
    skill_id: str,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    """更新用户 Skill（仅 draft 状态的 Skill 可修改正文）。"""
    result = await session.execute(
        select(UserSkill).where(UserSkill.id == skill_id)
    )
    skill = result.scalar_one_or_none()
    if not skill:
        return None

    # 更新可修改字段
    for field in ("display_name", "description", "tags", "required_tools", "scope"):
        if field in data:
            setattr(skill, field, data[field])

    # 正文修改 → 重置为 draft
    if "body" in data:
        skill.body = data["body"]
        skill.status = "draft"
        skill.validation_result = None

    skill.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(skill)
    return _skill_to_dict(skill)


async def delete_user_skill(
    session: AsyncSession,
    skill_id: str,
) -> bool:
    """删除用户 Skill。"""
    result = await session.execute(
        select(UserSkill).where(UserSkill.id == skill_id)
    )
    skill = result.scalar_one_or_none()
    if not skill:
        return False
    await session.delete(skill)
    await session.commit()
    logger.info(f"[Skill] 删除用户 Skill: {skill.name} (id={skill_id})")
    return True


async def toggle_user_skill(
    session: AsyncSession,
    skill_id: str,
) -> dict[str, Any] | None:
    """切换 Skill 启用状态。"""
    result = await session.execute(
        select(UserSkill).where(UserSkill.id == skill_id)
    )
    skill = result.scalar_one_or_none()
    if not skill:
        return None
    skill.is_enabled = not skill.is_enabled
    skill.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(skill)
    logger.info(f"[Skill] 切换 Skill 状态: {skill.name} enabled={skill.is_enabled}")
    return _skill_to_dict(skill)


async def validate_user_skill(
    session: AsyncSession,
    skill_id: str,
) -> dict[str, Any] | None:
    """
    校验用户 Skill — 检查格式、必要字段、冲突。
    校验通过后状态变为 validated，可以启用。
    """
    result = await session.execute(
        select(UserSkill).where(UserSkill.id == skill_id)
    )
    skill = result.scalar_one_or_none()
    if not skill:
        return None

    issues: list[str] = []

    # 1. 基本格式校验
    if not skill.body or len(skill.body.strip()) < 50:
        issues.append("Skill 正文过短（至少50字符）")
    if not skill.name or len(skill.name) < 2:
        issues.append("Skill 名称过短（至少2字符）")
    if not skill.description:
        issues.append("缺少 Skill 描述")

    # 2. 检查与系统 Skill 的名称冲突
    if skill.name in SYSTEM_SKILLS:
        issues.append(f"名称 '{skill.name}' 与系统 Skill 冲突")

    # 3. 检查 required_tools 是否有效
    from app.core.tool_dispatch import get_tool_names_for_user
    valid_tools = set(await get_tool_names_for_user(session, skill.user_id))
    if skill.required_tools:
        required = [t.strip() for t in skill.required_tools.split(",") if t.strip()]
        invalid = [t for t in required if t not in valid_tools and t != "load_skill"]
        if invalid:
            issues.append(f"依赖的工具不存在: {', '.join(invalid)}")

    # 更新校验结果
    validation = {
        "passed": len(issues) == 0,
        "issues": issues,
        "validated_at": datetime.utcnow().isoformat(),
    }
    skill.validation_result = validation
    skill.validated_at = datetime.utcnow() if not issues else None
    skill.status = "validated" if not issues else "draft"
    await session.commit()
    await session.refresh(skill)

    logger.info(f"[Skill] 校验 Skill: {skill.name} passed={not issues}")
    return _skill_to_dict(skill)


async def get_enabled_user_skills(
    session: AsyncSession,
    user_id: str,
) -> list[dict[str, Any]]:
    """获取用户已启用的自定义 Skill 列表（含正文）。"""
    stmt = (
        select(UserSkill)
        .where(UserSkill.user_id == user_id)
        .where(UserSkill.is_enabled == True)  # noqa: E712
        .order_by(UserSkill.name)
    )
    result = await session.execute(stmt)
    return [_skill_to_dict(s, include_body=True) for s in result.scalars().all()]


async def increment_skill_usage(
    session: AsyncSession,
    skill_id: str,
) -> None:
    """递增 Skill 使用次数。"""
    await session.execute(
        update(UserSkill)
        .where(UserSkill.id == skill_id)
        .values(usage_count=UserSkill.usage_count + 1)
    )
    await session.commit()


def _skill_to_dict(skill: UserSkill, include_body: bool = False) -> dict[str, Any]:
    """将 UserSkill ORM 对象序列化为字典。"""
    d = {
        "id": skill.id,
        "name": skill.name,
        "display_name": skill.display_name,
        "description": skill.description,
        "tags": skill.tags,
        "required_tools": skill.required_tools,
        "status": skill.status,
        "is_enabled": skill.is_enabled,
        "scope": skill.scope,
        "validation_result": skill.validation_result,
        "usage_count": skill.usage_count,
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
    }
    if include_body:
        d["body"] = skill.body
    return d
