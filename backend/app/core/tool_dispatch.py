"""
Tool 调度器 — 自动扫描 app/tools/ 目录, 注册所有 Tool。
每个 Tool 文件需暴露:
  - TOOL_DEFINITION: dict  (OpenAI function-calling JSON Schema)
  - async def execute(params: dict) -> dict
"""
import asyncio
import importlib
import logging
import os
import pkgutil
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ──────────────── 工具分类系统 ────────────────
# 按意图/场景对工具分类, 支持按任务类型过滤下发给 LLM 的工具列表
# 减少 token 消耗并降低 LLM 调用错误工具的概率

class ToolCategory:
    """工具类别常量。"""
    RESEARCH = "research"          # 研究类: web_search, fetch_url, parse_document
    PPT = "ppt"                    # PPT/Deck类: generate_ppt_deck, edit_slide, generate_slide, generate_outline
    DIAGRAM = "diagram"            # Draw.io/流程图类: display_diagram, edit_diagram, append_diagram
    CODE_ANALYSIS = "code"         # 代码分析类: parse_project, read_project_file
    MEMORY = "memory"              # 记忆类: save_to_memory, search_memory
    MEDIA = "media"                # 媒体类: image_search
    UTILITY = "utility"            # 通用类: load_skill
    UNIVERSAL = "universal"        # 所有场景都可用

# 工具名 → 类别映射
TOOL_CATEGORIES: dict[str, list[str]] = {
    "web_search":        [ToolCategory.RESEARCH, ToolCategory.UNIVERSAL],
    "fetch_url":         [ToolCategory.RESEARCH],
    "parse_document":    [ToolCategory.RESEARCH, ToolCategory.UNIVERSAL],
    "parse_project":     [ToolCategory.CODE_ANALYSIS],
    "read_project_file": [ToolCategory.CODE_ANALYSIS],
    "image_search":      [ToolCategory.MEDIA, ToolCategory.RESEARCH],
    "edit_deck_page":             [ToolCategory.PPT],
    "retry_failed_deck_pages":    [ToolCategory.PPT],
    "display_diagram":   [ToolCategory.DIAGRAM],
    "edit_diagram":      [ToolCategory.DIAGRAM],
    "append_diagram":    [ToolCategory.DIAGRAM],
    "get_current_diagram": [ToolCategory.DIAGRAM],
    "get_shape_library": [ToolCategory.DIAGRAM],
    "save_to_memory":    [ToolCategory.MEMORY, ToolCategory.UNIVERSAL],
    "search_memory":     [ToolCategory.MEMORY, ToolCategory.UNIVERSAL],
    "load_skill":        [ToolCategory.UTILITY, ToolCategory.UNIVERSAL],
    "dispatch_subagent": [ToolCategory.UNIVERSAL],
    "run_code":          [ToolCategory.CODE_ANALYSIS, ToolCategory.UTILITY, ToolCategory.UNIVERSAL],
}

# 意图 → 允许的工具类别映射
INTENT_ALLOWED_CATEGORIES: dict[str, set[str]] = {
    "research":      {ToolCategory.RESEARCH, ToolCategory.MEMORY, ToolCategory.UTILITY, ToolCategory.UNIVERSAL, ToolCategory.MEDIA, ToolCategory.DIAGRAM},
    "ppt":           {ToolCategory.PPT, ToolCategory.RESEARCH, ToolCategory.MEMORY, ToolCategory.UTILITY, ToolCategory.UNIVERSAL, ToolCategory.MEDIA, ToolCategory.DIAGRAM},
    "code_analysis": {ToolCategory.CODE_ANALYSIS, ToolCategory.RESEARCH, ToolCategory.MEMORY, ToolCategory.UTILITY, ToolCategory.UNIVERSAL, ToolCategory.DIAGRAM},
    "chat":          {ToolCategory.RESEARCH, ToolCategory.MEMORY, ToolCategory.UTILITY, ToolCategory.UNIVERSAL, ToolCategory.DIAGRAM},
    "composite":     None,  # None 表示所有类别都允许
}


def get_tool_categories(tool_name: str) -> list[str]:
    """获取工具所属类别列表。"""
    return TOOL_CATEGORIES.get(tool_name, [ToolCategory.UNIVERSAL])


def filter_tools_by_intent(
    tools: list[dict[str, Any]],
    intent: str | None,
) -> list[dict[str, Any]]:
    """根据检测到的意图过滤工具列表。

    Args:
        tools: 完整的工具定义列表
        intent: 检测到的用户意图 (research/ppt/code_analysis/chat/composite)

    Returns:
        过滤后的工具列表。如果 intent 为 None 或 composite，返回全部工具。
    """
    if not intent:
        return tools

    allowed_categories = INTENT_ALLOWED_CATEGORIES.get(intent)
    if allowed_categories is None:
        # composite 或未知意图 → 返回全部
        return tools

    filtered = []
    for tool in tools:
        tool_name = tool.get("function", {}).get("name", "")
        categories = get_tool_categories(tool_name)
        # 工具的任一类别在允许列表中即可通过
        if any(cat in allowed_categories for cat in categories):
            filtered.append(tool)

    return filtered

# ──────────────── 全局 Tool 注册表 ────────────────
_registry: dict[str, dict[str, Any]] = {}
# 结构: { "tool_name": { "definition": {...}, "execute": <coroutine function>, "metadata": {...} } }

DEFAULT_TOOL_RUNTIME_METADATA: dict[str, Any] = {
    "expose_to_llm": True,
    "status": "stable",
    "replacement": None,
}

TOOL_TIMEOUT_OVERRIDES: dict[str, float] = {
    "dispatch_subagent": 300.0,
    "run_code": 240.0,
    "edit_deck_page": 240.0,
    "regenerate_deck_page": 420.0,
}

# ────────────── Tool Middleware ──────────────
_pre_hooks: list[Callable] = []
_post_hooks: list[Callable] = []


def register_pre_hook(hook: Callable) -> None:
    """Register a pre-execution hook. Hook signature: async (tool_name, params) -> params or None.
    Returning None means skip execution (useful for blocking/filtering).
    Returning modified params allows parameter transformation."""
    _pre_hooks.append(hook)


def register_post_hook(hook: Callable) -> None:
    """Register a post-execution hook. Hook signature: async (tool_name, params, result) -> result.
    Can transform or log tool results."""
    _post_hooks.append(hook)


def _normalize_runtime_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(DEFAULT_TOOL_RUNTIME_METADATA)
    if metadata:
        normalized.update(metadata)
    return normalized


def get_tool_definitions(include_hidden: bool = False) -> list[dict[str, Any]]:
    """返回供 LLM function-calling 使用的 Tool 定义列表。"""
    definitions: list[dict[str, Any]] = []
    for entry in _registry.values():
        metadata = entry.get("metadata", DEFAULT_TOOL_RUNTIME_METADATA)
        if not include_hidden and not metadata.get("expose_to_llm", True):
            continue
        definitions.append(deepcopy(entry["definition"]))
    return definitions


def get_tool_names(include_hidden: bool = True) -> list[str]:
    """返回已注册 Tool 名称。"""
    if include_hidden:
        return list(_registry.keys())
    return [
        name
        for name, entry in _registry.items()
        if entry.get("metadata", DEFAULT_TOOL_RUNTIME_METADATA).get("expose_to_llm", True)
    ]


def get_tool_runtime_metadata(tool_name: str) -> dict[str, Any] | None:
    """返回指定 Tool 的运行时元数据。"""
    entry = _registry.get(tool_name)
    if not entry:
        return None
    return dict(entry.get("metadata", DEFAULT_TOOL_RUNTIME_METADATA))


async def get_tool_definitions_for_user(
    session: AsyncSession,
    user_id: str,
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    """返回静态 Tool + 当前用户已启用外部 tool_adapter 暴露的动态 Tool。"""
    definitions = get_tool_definitions(include_hidden=include_hidden)
    dynamic_entries = await _get_dynamic_tool_entries(
        session,
        user_id,
        include_hidden=include_hidden,
        reserved_names=set(_registry.keys()),
    )
    definitions.extend(deepcopy(entry["definition"]) for entry in dynamic_entries)
    return definitions


async def get_tool_names_for_user(
    session: AsyncSession,
    user_id: str,
    include_hidden: bool = True,
) -> list[str]:
    """返回静态 Tool 名称 + 当前用户动态 Tool 名称。"""
    names = get_tool_names(include_hidden=include_hidden)
    dynamic_entries = await _get_dynamic_tool_entries(
        session,
        user_id,
        include_hidden=include_hidden,
        reserved_names=set(_registry.keys()),
    )
    names.extend(entry["name"] for entry in dynamic_entries)
    return names


async def dispatch(
    tool_name: str,
    params: dict[str, Any],
    *,
    session: AsyncSession | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    根据名称调度 Tool 执行。

    Args:
        tool_name: Tool 名称（需与 TOOL_DEFINITION.function.name 一致）
        params: LLM 提供的参数 dict

    Returns:
        Tool 执行结果 dict

    Raises:
        ValueError: Tool 未注册
    """
    entry = _registry.get(tool_name)
    if entry is not None:
        logger.info(f"[ToolDispatch] 执行 {tool_name}，参数: {params}")

        # Run pre-hooks
        for hook in _pre_hooks:
            try:
                hook_result = await hook(tool_name, params)
                if hook_result is None:
                    return {"blocked": True, "tool": tool_name, "reason": "blocked by pre-hook"}
                params = hook_result
            except Exception as e:
                logger.warning(f"Pre-hook error for {tool_name}: {e}")

        tool_timeout = TOOL_TIMEOUT_OVERRIDES.get(tool_name, 60.0)

        try:
            try:
                result = await asyncio.wait_for(entry["execute"](params), timeout=tool_timeout)
            except asyncio.TimeoutError:
                result = {"error": f"工具 {tool_name} 执行超时，请稍后重试", "tool": tool_name, "timeout": True}

            # Run post-hooks
            for hook in _post_hooks:
                try:
                    result = await hook(tool_name, params, result)
                except Exception as e:
                    logger.warning(f"Post-hook error for {tool_name}: {e}")

            logger.info(f"[ToolDispatch] {tool_name} 执行成功")
            return result
        except Exception as e:
            logger.exception(f"[ToolDispatch] {tool_name} 执行失败: {e}")
            error_msg = str(e).split("\n")[0][:200]
            return {"error": f"工具执行失败: {error_msg}", "tool": tool_name}

    dynamic_entry = None
    if session is not None and user_id:
        dynamic_entry = await _get_dynamic_tool_entry(session, user_id, tool_name)

    if dynamic_entry is None:
        raise ValueError(f"未知 Tool: {tool_name}，可用 Tool: {list(_registry.keys())}")

    logger.info(
        "[ToolDispatch] 执行动态 Tool: %s (package=%s@%s, adapter=%s)",
        tool_name,
        dynamic_entry["package_id"],
        dynamic_entry["package_version"],
        dynamic_entry["adapter_target"],
    )

    try:
        from app.services.package_runtime import invoke_tool_adapter_package

        result = await invoke_tool_adapter_package(
            session,
            user_id,
            package_id=dynamic_entry["package_id"],
            adapter_target=dynamic_entry["adapter_target"],
            params=params,
            tool_name=tool_name,
        )
        logger.info("[ToolDispatch] 动态 Tool %s 执行成功", tool_name)
        return result
    except Exception as e:
        logger.exception(f"[ToolDispatch] 动态 Tool {tool_name} 执行失败: {e}")
        return {"error": str(e), "tool": tool_name}


def register_tool(
    name: str,
    definition: dict[str, Any],
    execute_fn,
    metadata: dict[str, Any] | None = None,
) -> None:
    """手动注册一个 Tool。"""
    runtime_metadata = _normalize_runtime_metadata(metadata)
    _registry[name] = {
        "definition": definition,
        "execute": execute_fn,
        "metadata": runtime_metadata,
    }
    logger.info(
        "[ToolDispatch] 注册 Tool: %s (expose_to_llm=%s, status=%s)",
        name,
        runtime_metadata.get("expose_to_llm", True),
        runtime_metadata.get("status", "stable"),
    )


def auto_discover_tools() -> None:
    """
    自动扫描 app/tools/ 目录下所有 Python 模块，
    提取 TOOL_DEFINITION 和 execute 函数并注册。
    """
    import app.tools as tools_pkg

    package_path = os.path.dirname(tools_pkg.__file__)

    for importer, module_name, is_pkg in pkgutil.iter_modules([package_path]):
        if module_name.startswith("_"):
            continue  # 跳过 __init__ 等

        try:
            module = importlib.import_module(f"app.tools.{module_name}")
        except Exception as e:
            logger.warning(f"[ToolDispatch] 无法导入 app.tools.{module_name}: {e}")
            continue

        definition = getattr(module, "TOOL_DEFINITION", None)
        execute_fn = getattr(module, "execute", None)
        runtime_metadata = getattr(module, "TOOL_RUNTIME_METADATA", None)

        if definition is None or execute_fn is None:
            logger.warning(
                f"[ToolDispatch] app.tools.{module_name} 缺少 TOOL_DEFINITION 或 execute，跳过"
            )
            continue

        # 从 definition 提取 tool 名称
        func_name = definition.get("function", {}).get("name", module_name)
        register_tool(func_name, definition, execute_fn, runtime_metadata)

    logger.info(f"[ToolDispatch] 自动发现完成，共注册 {len(_registry)} 个 Tool: {list(_registry.keys())}")


async def _get_dynamic_tool_entry(
    session: AsyncSession,
    user_id: str,
    tool_name: str,
) -> dict[str, Any] | None:
    entries = await _get_dynamic_tool_entries(
        session,
        user_id,
        include_hidden=True,
        reserved_names=set(_registry.keys()),
    )
    return next((entry for entry in entries if entry["name"] == tool_name), None)


async def _get_dynamic_tool_entries(
    session: AsyncSession,
    user_id: str,
    *,
    include_hidden: bool,
    reserved_names: set[str],
) -> list[dict[str, Any]]:
    from app.models.tables import InstalledPlugin, PluginVersion

    result = await session.execute(
        select(InstalledPlugin, PluginVersion)
        .join(PluginVersion, PluginVersion.id == InstalledPlugin.active_version_id)
        .where(InstalledPlugin.user_id == user_id)
        .where(InstalledPlugin.package_kind == "tool_adapter")
        .where(InstalledPlugin.is_enabled == True)  # noqa: E712
        .order_by(InstalledPlugin.package_id)
    )

    entries: list[dict[str, Any]] = []
    seen_names = set(reserved_names)

    for installed, version_row in result.all():
        resource_manifest = version_row.resource_manifest if isinstance(version_row.resource_manifest, dict) else {}
        raw_tools = resource_manifest.get("llm_tools")
        if not isinstance(raw_tools, list):
            continue

        adapter_targets = {
            str(item.get("target") or "").strip()
            for item in (version_row.entrypoints or [])
            if isinstance(item, dict) and item.get("kind") == "adapter"
        }

        for raw_tool in raw_tools:
            entry = _normalize_dynamic_tool_entry(
                raw_tool,
                package_id=installed.package_id,
                package_version=installed.version,
                adapter_targets=adapter_targets,
            )
            if entry is None:
                continue
            if entry["name"] in seen_names:
                logger.warning(
                    "[ToolDispatch] 跳过动态 Tool %s，名称冲突（package=%s）",
                    entry["name"],
                    installed.package_id,
                )
                continue
            if not include_hidden and not entry["metadata"].get("expose_to_llm", True):
                continue

            seen_names.add(entry["name"])
            entries.append(entry)

    return entries


def _normalize_dynamic_tool_entry(
    raw_tool: Any,
    *,
    package_id: str,
    package_version: str,
    adapter_targets: set[str],
) -> dict[str, Any] | None:
    if not isinstance(raw_tool, dict):
        return None

    adapter_target = str(
        raw_tool.get("adapter_target")
        or raw_tool.get("entrypoint_target")
        or raw_tool.get("target")
        or ""
    ).strip()
    if not adapter_target or adapter_target not in adapter_targets:
        logger.warning(
            "[ToolDispatch] 跳过动态 Tool，adapter_target 无效: package=%s target=%s",
            package_id,
            adapter_target or "<empty>",
        )
        return None

    metadata_source = raw_tool.get("runtime_metadata")
    if not isinstance(metadata_source, dict):
        metadata_source = raw_tool.get("metadata") if isinstance(raw_tool.get("metadata"), dict) else None
    metadata = _normalize_runtime_metadata(metadata_source)
    if "expose_to_llm" in raw_tool:
        metadata["expose_to_llm"] = bool(raw_tool.get("expose_to_llm"))
    if isinstance(raw_tool.get("status"), str):
        metadata["status"] = raw_tool["status"]

    definition = raw_tool.get("definition") if isinstance(raw_tool.get("definition"), dict) else None
    if definition is None:
        tool_name = str(raw_tool.get("name") or "").strip()
        if not tool_name:
            return None
        definition = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": str(raw_tool.get("description") or f"Invoke {package_id} adapter {adapter_target}.").strip(),
                "parameters": raw_tool.get("parameters") if isinstance(raw_tool.get("parameters"), dict) else {
                    "type": "object",
                    "properties": {},
                },
            },
        }
    else:
        definition = deepcopy(definition)
        definition.setdefault("type", "function")

    function_block = definition.get("function")
    if not isinstance(function_block, dict):
        return None

    tool_name = str(function_block.get("name") or "").strip()
    if not tool_name:
        return None

    if not isinstance(function_block.get("parameters"), dict):
        function_block["parameters"] = {"type": "object", "properties": {}}
    if not function_block.get("description"):
        function_block["description"] = f"Invoke {package_id} adapter {adapter_target}."

    return {
        "name": tool_name,
        "definition": definition,
        "metadata": metadata,
        "package_id": package_id,
        "package_version": package_version,
        "adapter_target": adapter_target,
    }
