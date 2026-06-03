"""Remote package source importers for external plugin repositories."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
import re
from typing import Any, Literal

import httpx


GITHUB_API_BASE = "https://api.github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"
HTTP_TIMEOUT = 20.0


@dataclass(frozen=True)
class GitHubRemoteSource:
    source_id: str
    owner: str
    repo: str
    ref: str
    package_id: str
    plugin_path: str
    package_kind: Literal["workflow", "tool_adapter"] = "workflow"
    related_skill_path: str | None = None
    adapter_targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class RemotePackageBundle:
    source_id: str
    package_id: str
    source_ref: str
    manifest: dict[str, Any]
    resource_manifest: dict[str, Any]
    integrity_hash: str
    upstream_version: str
    commit_sha: str
    commit_date: str


REMOTE_PACKAGE_SOURCES: dict[str, GitHubRemoteSource] = {
    "minimax.pptx-plugin": GitHubRemoteSource(
        source_id="minimax.pptx-plugin",
        owner="MiniMax-AI",
        repo="skills",
        ref="main",
        package_id="minimax.pptx-plugin",
        plugin_path="plugins/pptx-plugin",
        related_skill_path="skills/pptx-generator",
    ),
}


def build_custom_source_id(owner: str, repo: str, plugin_path: str, ref: str) -> str:
    normalized_path = plugin_path.strip("/") or "."
    return f"github:{owner}/{repo}/{normalized_path}@{ref}"


def infer_package_id(owner: str, repo: str, plugin_path: str) -> str:
    base = plugin_path.strip("/").split("/")[-1] or repo
    normalized_owner = re.sub(r"[^a-z0-9]+", "-", owner.lower()).strip("-") or "github"
    normalized_base = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") or "package"
    return f"{normalized_owner}.{normalized_base}"


def create_github_remote_source(
    *,
    owner: str,
    repo: str,
    ref: str,
    plugin_path: str,
    package_id: str,
    package_kind: Literal["workflow", "tool_adapter"],
    related_skill_path: str | None = None,
    adapter_targets: tuple[str, ...] = (),
    source_id: str | None = None,
) -> GitHubRemoteSource:
    cleaned_ref = (ref or "main").strip() or "main"
    cleaned_path = plugin_path.strip("/")
    if not cleaned_path:
        raise ValueError("plugin_path 不能为空")

    return GitHubRemoteSource(
        source_id=source_id or build_custom_source_id(owner, repo, cleaned_path, cleaned_ref),
        owner=owner.strip(),
        repo=repo.strip(),
        ref=cleaned_ref,
        package_id=package_id.strip(),
        plugin_path=cleaned_path,
        package_kind=package_kind,
        related_skill_path=(related_skill_path or None),
        adapter_targets=adapter_targets,
    )


class RemotePackageImportError(RuntimeError):
    """Raised when a remote package source cannot be imported."""


async def fetch_remote_package_bundle(source_id: str) -> RemotePackageBundle:
    if os.getenv("OFFLINE_MODE", "").lower() == "true":
        raise ValueError(f"离线模式：跳过远程插件拉取 ({source_id})")
    spec = REMOTE_PACKAGE_SOURCES.get(source_id)
    if spec is None:
        raise ValueError("未知的远端包源")

    return await fetch_remote_package_bundle_from_spec(spec)


async def fetch_remote_package_bundle_from_spec(spec: GitHubRemoteSource) -> RemotePackageBundle:
    """Fetch a remote bundle from an explicit GitHub source spec."""

    if spec.source_id == "minimax.pptx-plugin":
        raise RemotePackageImportError("minimax.pptx-plugin 已下线，因为平台已移除原生 PPTX 导出链路")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=_github_headers()) as client:
        if spec.package_kind == "tool_adapter":
            return await _fetch_tool_adapter_bundle(client, spec)
        return await _fetch_minimax_pptx_plugin_bundle(client, spec)


def get_remote_source_summary(source_id: str) -> dict[str, Any] | None:
    spec = REMOTE_PACKAGE_SOURCES.get(source_id)
    if spec is None:
        return None
    return {
        "source_id": spec.source_id,
        "package_id": spec.package_id,
        "package_kind": spec.package_kind,
        "provider": "github",
        "source_ref": f"github:{spec.owner}/{spec.repo}/{spec.plugin_path}@{spec.ref}",
        "repo_url": f"https://github.com/{spec.owner}/{spec.repo}/tree/{spec.ref}/{spec.plugin_path}",
    }


async def _fetch_minimax_pptx_plugin_bundle(
    client: httpx.AsyncClient,
    spec: GitHubRemoteSource,
) -> RemotePackageBundle:
    root_items, skill_dirs, agent_files, plugin_json, marketplace_json, readme_text, commit_info, related_skill = await asyncio.gather(
        _github_list_dir(client, spec.owner, spec.repo, spec.plugin_path, spec.ref),
        _github_list_dir(client, spec.owner, spec.repo, f"{spec.plugin_path}/skills", spec.ref),
        _github_list_dir(client, spec.owner, spec.repo, f"{spec.plugin_path}/agents", spec.ref),
        _github_fetch_json_file(client, spec.owner, spec.repo, f"{spec.plugin_path}/.claude-plugin/plugin.json", spec.ref),
        _github_fetch_json_file(client, spec.owner, spec.repo, f"{spec.plugin_path}/.claude-plugin/marketplace.json", spec.ref),
        _github_fetch_text_file(client, spec.owner, spec.repo, f"{spec.plugin_path}/README.md", spec.ref),
        _github_latest_commit(client, spec.owner, spec.repo, spec.plugin_path, spec.ref),
        _fetch_related_skillset(client, spec),
    )

    skill_specs = [
        item for item in skill_dirs if item.get("type") == "dir"
    ]
    agent_specs = [
        item for item in agent_files if item.get("type") == "file" and str(item.get("name", "")).endswith(".md")
    ]

    skills = await _fetch_plugin_skills(client, spec, skill_specs)
    agents = await _fetch_plugin_agents(client, spec, agent_specs)

    package_name = _normalize_space(str(plugin_json.get("name") or marketplace_json.get("name") or spec.package_id))
    upstream_version = _normalize_semver_candidate(
        str(
            plugin_json.get("version")
            or ((marketplace_json.get("metadata") or {}).get("version"))
            or "1.0.0"
        )
    )
    description = _normalize_space(
        str(
            plugin_json.get("description")
            or ((marketplace_json.get("metadata") or {}).get("description"))
            or _extract_first_paragraph(readme_text)
            or "MiniMax PPT generation and editing plugin."
        )
    )

    commit_sha = str(commit_info.get("sha") or "")
    commit_date = str(((commit_info.get("commit") or {}).get("author") or {}).get("date") or "")
    commit_short = commit_sha[:12] if commit_sha else "unknown"

    manifest = {
        "schema_version": "1.0.0",
        "package_id": spec.package_id,
        "display_name": "MiniMax PPTX Plugin",
        "kind": "workflow",
        "version": upstream_version,
        "description": description,
        "publisher": f"{spec.owner}/{spec.repo}",
        "tags": ["minimax", "pptx", "plugin", "workflow", "remote", "github"],
        "capabilities": _derive_remote_capabilities(skills, agents, readme_text),
        "permissions": [
            {"name": "model.invoke", "rationale": "执行多页 PPT 工作流规划与审查"},
            {"name": "asset.read", "rationale": "读取模板、素材和既有演示文稿"},
            {"name": "document.parse", "rationale": "解析文档与 PPT 文本内容以支持工作流"},
        ],
        "dependencies": [
            {"package_id": "minimax.pptx-generator-skillset", "version_constraint": ">=0.2.0"},
            {"package_id": "official.html-preview-renderer", "version_constraint": ">=0.2.0", "optional": True},
        ],
        "compatibility": {
            "min_platform_version": "0.1.0",
            "target_artifact_mode": ["dual_render"],
        },
        "entrypoints": [
            {
                "kind": "workflow",
                "target": "workflows/minimax-pptx-plugin",
                "description": "使用 MiniMax 官方远端插件语义编排原生 PPTX 工作流。",
            }
        ],
        "metadata": {
            "release_date": commit_date[:10] if commit_date else datetime.utcnow().strftime("%Y-%m-%d"),
            "release_notes": f"Imported from {spec.owner}/{spec.repo}@{commit_short}",
            "upgrade_notes": "重新导入远端包源即可拉取上游更新。",
            "source_repo": f"{spec.owner}/{spec.repo}",
            "source_path": spec.plugin_path,
            "source_commit": commit_short,
            "upstream_version": upstream_version,
        },
    }

    resource_manifest = {
        "remote_source": {
            "provider": "github",
            "owner": spec.owner,
            "repo": spec.repo,
            "ref": spec.ref,
            "plugin_path": spec.plugin_path,
            "package_root_url": f"https://github.com/{spec.owner}/{spec.repo}/tree/{spec.ref}/{spec.plugin_path}",
            "commit_sha": commit_sha,
            "commit_date": commit_date,
        },
        "root_entries": [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "type": item.get("type"),
                "download_url": item.get("download_url"),
                "html_url": item.get("html_url"),
            }
            for item in root_items
        ],
        "plugin_config": plugin_json,
        "marketplace": marketplace_json,
        "readme": {
            "path": f"{spec.plugin_path}/README.md",
            "download_url": _raw_url(spec.owner, spec.repo, spec.ref, f"{spec.plugin_path}/README.md"),
            "body": readme_text,
        },
        "skills": skills,
        "agents": agents,
        "related_skillset": related_skill,
    }

    integrity_hash = hashlib.sha256(
        json.dumps(
            {
                "manifest": manifest,
                "resource_manifest": resource_manifest,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    return RemotePackageBundle(
        source_id=spec.source_id,
        package_id=spec.package_id,
        source_ref=f"github:{spec.owner}/{spec.repo}/{spec.plugin_path}@{spec.ref}",
        manifest=manifest,
        resource_manifest=resource_manifest,
        integrity_hash=integrity_hash,
        upstream_version=upstream_version,
        commit_sha=commit_sha,
        commit_date=commit_date,
    )


async def _fetch_tool_adapter_bundle(
    client: httpx.AsyncClient,
    spec: GitHubRemoteSource,
) -> RemotePackageBundle:
    root_items, plugin_json, marketplace_json, readme_text, commit_info = await asyncio.gather(
        _github_list_dir(client, spec.owner, spec.repo, spec.plugin_path, spec.ref),
        _github_fetch_json_file_optional(client, spec.owner, spec.repo, f"{spec.plugin_path}/.claude-plugin/plugin.json", spec.ref),
        _github_fetch_json_file_optional(client, spec.owner, spec.repo, f"{spec.plugin_path}/.claude-plugin/marketplace.json", spec.ref),
        _github_fetch_text_file_optional(client, spec.owner, spec.repo, f"{spec.plugin_path}/README.md", spec.ref),
        _github_latest_commit(client, spec.owner, spec.repo, spec.plugin_path, spec.ref),
    )

    adapter_config = _extract_tool_adapter_config(plugin_json, marketplace_json)
    package_name = _normalize_space(
        str(
            adapter_config.get("display_name")
            or plugin_json.get("name")
            or marketplace_json.get("name")
            or spec.package_id
        )
    )
    upstream_version = _normalize_semver_candidate(
        str(
            adapter_config.get("version")
            or plugin_json.get("version")
            or ((marketplace_json.get("metadata") or {}).get("version"))
            or "1.0.0"
        )
    )
    description = _normalize_space(
        str(
            adapter_config.get("description")
            or plugin_json.get("description")
            or ((marketplace_json.get("metadata") or {}).get("description"))
            or _extract_first_paragraph(readme_text)
            or f"Tool adapter package imported from {spec.owner}/{spec.repo}."
        )
    )

    commit_sha = str(commit_info.get("sha") or "")
    commit_date = str(((commit_info.get("commit") or {}).get("author") or {}).get("date") or "")
    commit_short = commit_sha[:12] if commit_sha else "unknown"

    entrypoints = _derive_tool_adapter_entrypoints(
        spec,
        adapter_config=adapter_config,
        readme_text=readme_text,
    )
    llm_tools = _derive_tool_adapter_llm_tools(
        package_id=spec.package_id,
        display_name=package_name,
        description=description,
        entrypoints=entrypoints,
        adapter_config=adapter_config,
        plugin_json=plugin_json,
        marketplace_json=marketplace_json,
    )

    manifest = {
        "schema_version": "1.0.0",
        "package_id": spec.package_id,
        "display_name": package_name,
        "kind": "tool_adapter",
        "version": upstream_version,
        "description": description,
        "publisher": f"{spec.owner}/{spec.repo}",
        "tags": _derive_tool_adapter_tags(spec, adapter_config, package_name, readme_text),
        "capabilities": _derive_tool_adapter_capabilities(entrypoints),
        "permissions": _derive_tool_adapter_permissions(entrypoints),
        "dependencies": _derive_tool_adapter_dependencies(entrypoints),
        "compatibility": {
            "min_platform_version": "0.1.0",
            "target_artifact_mode": ["native_pptx_first", "dual_render"],
        },
        "entrypoints": entrypoints,
        "metadata": {
            "release_date": commit_date[:10] if commit_date else datetime.utcnow().strftime("%Y-%m-%d"),
            "release_notes": f"Imported from {spec.owner}/{spec.repo}@{commit_short}",
            "upgrade_notes": "重新导入远端包源即可拉取上游更新。",
            "source_repo": f"{spec.owner}/{spec.repo}",
            "source_path": spec.plugin_path,
            "source_commit": commit_short,
            "upstream_version": upstream_version,
        },
    }

    resource_manifest = {
        "remote_source": {
            "provider": "github",
            "owner": spec.owner,
            "repo": spec.repo,
            "ref": spec.ref,
            "plugin_path": spec.plugin_path,
            "package_root_url": f"https://github.com/{spec.owner}/{spec.repo}/tree/{spec.ref}/{spec.plugin_path}",
            "commit_sha": commit_sha,
            "commit_date": commit_date,
        },
        "root_entries": [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "type": item.get("type"),
                "download_url": item.get("download_url"),
                "html_url": item.get("html_url"),
            }
            for item in root_items
        ],
        "plugin_config": plugin_json,
        "marketplace": marketplace_json,
        "readme": {
            "path": f"{spec.plugin_path}/README.md",
            "download_url": _raw_url(spec.owner, spec.repo, spec.ref, f"{spec.plugin_path}/README.md"),
            "body": readme_text,
        },
        "llm_tools": llm_tools,
        "adapter_config": adapter_config,
    }

    integrity_hash = hashlib.sha256(
        json.dumps(
            {
                "manifest": manifest,
                "resource_manifest": resource_manifest,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    return RemotePackageBundle(
        source_id=spec.source_id,
        package_id=spec.package_id,
        source_ref=f"github:{spec.owner}/{spec.repo}/{spec.plugin_path}@{spec.ref}",
        manifest=manifest,
        resource_manifest=resource_manifest,
        integrity_hash=integrity_hash,
        upstream_version=upstream_version,
        commit_sha=commit_sha,
        commit_date=commit_date,
    )


async def _fetch_plugin_skills(
    client: httpx.AsyncClient,
    spec: GitHubRemoteSource,
    skill_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tasks = [
        _fetch_single_skill(client, spec, skill_spec)
        for skill_spec in skill_specs
    ]
    results = await asyncio.gather(*tasks)
    return [item for item in results if item is not None]


async def _fetch_single_skill(
    client: httpx.AsyncClient,
    spec: GitHubRemoteSource,
    skill_spec: dict[str, Any],
) -> dict[str, Any] | None:
    skill_path = str(skill_spec.get("path") or "")
    if not skill_path:
        return None

    files = await _github_list_dir(client, spec.owner, spec.repo, skill_path, spec.ref)
    skill_file = next((item for item in files if item.get("name") == "SKILL.md"), None)
    if skill_file is None:
        return None

    body = await _github_fetch_download_url(client, str(skill_file.get("download_url") or _raw_url(spec.owner, spec.repo, spec.ref, f"{skill_path}/SKILL.md")))
    frontmatter, markdown_body = _parse_markdown_frontmatter(body)
    skill_id = str(frontmatter.get("name") or skill_spec.get("name") or skill_path.rsplit("/", 1)[-1])
    display_name = _humanize_skill_title(skill_id, _extract_markdown_title(markdown_body))
    description = _normalize_space(
        str(frontmatter.get("description") or _extract_first_paragraph(markdown_body) or display_name)
    )
    return {
        "skill_id": skill_id,
        "display_name": display_name,
        "description": description,
        "tags": _derive_skill_tags(skill_id, description),
        "required_tools": _derive_required_tools(skill_id, description, markdown_body),
        "body": body,
        "source_path": skill_path,
        "source_url": str(skill_file.get("html_url") or ""),
        "download_url": str(skill_file.get("download_url") or ""),
    }


async def _fetch_plugin_agents(
    client: httpx.AsyncClient,
    spec: GitHubRemoteSource,
    agent_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tasks = [
        _fetch_single_agent(client, spec, agent_spec)
        for agent_spec in agent_specs
    ]
    results = await asyncio.gather(*tasks)
    return [item for item in results if item is not None]


async def _fetch_single_agent(
    client: httpx.AsyncClient,
    spec: GitHubRemoteSource,
    agent_spec: dict[str, Any],
) -> dict[str, Any] | None:
    download_url = str(agent_spec.get("download_url") or "")
    if not download_url:
        return None
    body = await _github_fetch_download_url(client, download_url)
    name = str(agent_spec.get("name") or "agent")
    agent_id = name[:-3] if name.endswith(".md") else name
    return {
        "agent_id": agent_id,
        "display_name": _humanize_identifier(agent_id),
        "description": _extract_first_paragraph(body) or _humanize_identifier(agent_id),
        "body": body,
        "source_path": agent_spec.get("path"),
        "source_url": agent_spec.get("html_url"),
        "download_url": download_url,
    }


async def _fetch_related_skillset(
    client: httpx.AsyncClient,
    spec: GitHubRemoteSource,
) -> dict[str, Any] | None:
    if not spec.related_skill_path:
        return None
    try:
        skill_body = await _github_fetch_text_file(
            client,
            spec.owner,
            spec.repo,
            f"{spec.related_skill_path}/SKILL.md",
            spec.ref,
        )
        reference_items = await _github_list_dir(
            client,
            spec.owner,
            spec.repo,
            f"{spec.related_skill_path}/references",
            spec.ref,
        )
    except RemotePackageImportError:
        return None

    frontmatter, markdown_body = _parse_markdown_frontmatter(skill_body)
    return {
        "skill_id": str(frontmatter.get("name") or "pptx-generator"),
        "display_name": _humanize_skill_title(
            str(frontmatter.get("name") or "pptx-generator"),
            _extract_markdown_title(markdown_body),
        ),
        "description": _normalize_space(
            str(frontmatter.get("description") or _extract_first_paragraph(markdown_body) or "pptx-generator")
        ),
        "body": skill_body,
        "source_path": spec.related_skill_path,
        "source_url": f"https://github.com/{spec.owner}/{spec.repo}/tree/{spec.ref}/{spec.related_skill_path}",
        "references": [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "download_url": item.get("download_url"),
                "html_url": item.get("html_url"),
            }
            for item in reference_items
            if item.get("type") == "file"
        ],
    }


async def _github_latest_commit(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> dict[str, Any]:
    response = await client.get(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits",
        params={"path": path, "sha": ref, "per_page": 1},
    )
    if response.status_code >= 400:
        raise RemotePackageImportError(f"读取 GitHub commit 失败: {response.status_code}")
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        raise RemotePackageImportError("远端包源没有可用的 commit 信息")
    return payload[0]


async def _github_list_dir(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> list[dict[str, Any]]:
    response = await client.get(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
        params={"ref": ref},
    )
    if response.status_code >= 400:
        raise RemotePackageImportError(f"读取 GitHub 目录失败: {path} ({response.status_code})")
    payload = response.json()
    if isinstance(payload, list):
        return payload
    raise RemotePackageImportError(f"GitHub 目录返回异常: {path}")


async def _github_fetch_json_file(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> dict[str, Any]:
    text = await _github_fetch_text_file(client, owner, repo, path, ref)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RemotePackageImportError(f"远端 JSON 解析失败: {path}") from exc
    if not isinstance(payload, dict):
        raise RemotePackageImportError(f"远端 JSON 结构非法: {path}")
    return payload


async def _github_fetch_json_file_optional(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> dict[str, Any]:
    try:
        return await _github_fetch_json_file(client, owner, repo, path, ref)
    except RemotePackageImportError:
        return {}


async def _github_fetch_text_file(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> str:
    return await _github_fetch_download_url(client, _raw_url(owner, repo, ref, path))


async def _github_fetch_text_file_optional(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> str:
    try:
        return await _github_fetch_text_file(client, owner, repo, path, ref)
    except RemotePackageImportError:
        return ""


async def _github_fetch_download_url(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url)
    if response.status_code >= 400:
        raise RemotePackageImportError(f"读取远端文件失败: {url} ({response.status_code})")
    return response.text


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "GeneralAgent-RemotePackageImporter/1.0",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _raw_url(owner: str, repo: str, ref: str, path: str) -> str:
    return f"{GITHUB_RAW_BASE}/{owner}/{repo}/{ref}/{path}"


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_semver_candidate(value: str) -> str:
    candidate = value.strip() or "1.0.0"
    if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", candidate):
        return candidate
    return "1.0.0"


def _parse_markdown_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    frontmatter_lines: list[str] = []
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
        frontmatter_lines.append(line)
    if end_index is None:
        return {}, text

    metadata: dict[str, Any] = {}
    for line in frontmatter_lines:
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip().strip('"').strip("'")
        if key:
            metadata[key] = value
    body = "\n".join(lines[end_index + 1 :]).strip()
    return metadata, body


def _extract_markdown_title(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return None


def _extract_first_paragraph(text: str) -> str | None:
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
    for chunk in chunks:
        if chunk.startswith("---") or chunk.startswith("#"):
            continue
        cleaned = _normalize_space(re.sub(r"`([^`]+)`", r"\1", chunk))
        if cleaned:
            return cleaned
    return None


def _humanize_identifier(value: str) -> str:
    words = re.split(r"[-_]+", value.strip())
    return " ".join(word[:1].upper() + word[1:] for word in words if word)


def _humanize_skill_title(skill_id: str, heading: str | None) -> str:
    if heading:
        normalized_heading = _normalize_space(heading)
        if normalized_heading and normalized_heading.lower() not in {"readme", "skill"}:
            return normalized_heading
    return _humanize_identifier(skill_id)


def _derive_skill_tags(skill_id: str, description: str) -> list[str]:
    tags = ["minimax", "pptx", "plugin"]
    tags.extend(part for part in re.split(r"[-_]+", skill_id) if part)
    if "template" in description.lower():
        tags.append("template")
    if "qa" in description.lower() or "review" in description.lower():
        tags.append("qa")
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        normalized = tag.lower()
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _derive_required_tools(skill_id: str, description: str, body: str) -> list[str]:
    tools = ["load_skill"]
    lower_blob = f"{skill_id} {description} {body}".lower()
    if "markitdown" in lower_blob or "template" in lower_blob or "pptx" in lower_blob:
        tools.append("parse_document")
    if "search" in lower_blob or "research" in lower_blob:
        tools.append("web_search")
    seen: set[str] = set()
    return [tool for tool in tools if not (tool in seen or seen.add(tool))]


def _derive_remote_capabilities(
    skills: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    readme_text: str,
) -> list[str]:
    skill_ids = {str(item.get("skill_id") or "") for item in skills}
    capabilities = {
        "workflow.plugin_orchestration",
        "workflow.pptx_generation",
        "workflow.review_repair",
    }
    if "ppt-orchestra-skill" in skill_ids:
        capabilities.add("workflow.deck_planning")
    if "ppt-editing-skill" in skill_ids:
        capabilities.add("workflow.template_editing")
    if "slide-making-skill" in skill_ids:
        capabilities.add("workflow.slide_generation")
    if "design-style-skill" in skill_ids:
        capabilities.add("workflow.design_selection")
    if "color-font-skill" in skill_ids:
        capabilities.add("workflow.theme_selection")
    if agents:
        capabilities.add("workflow.subagent_generation")
    if "qa" in readme_text.lower():
        capabilities.add("workflow.text_only_qa")
    return sorted(capabilities)


def _extract_tool_adapter_config(
    plugin_json: dict[str, Any],
    marketplace_json: dict[str, Any],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    candidates: list[dict[str, Any]] = []

    for payload in (plugin_json, marketplace_json):
        if not isinstance(payload, dict):
            continue
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None
        for container in (payload, metadata):
            if not isinstance(container, dict):
                continue
            for key in ("generalagent", "general_agent", "tool_adapter", "toolAdapter"):
                value = container.get(key)
                if isinstance(value, dict):
                    candidates.append(value)
            if container.get("kind") == "tool_adapter" or container.get("package_kind") == "tool_adapter":
                inline = {
                    key: container.get(key)
                    for key in (
                        "display_name",
                        "description",
                        "version",
                        "tags",
                        "capabilities",
                        "permissions",
                        "dependencies",
                        "entrypoints",
                        "adapter_targets",
                        "llm_tools",
                        "tools",
                    )
                    if key in container
                }
                if inline:
                    candidates.append(inline)

    for candidate in candidates:
        merged = _deep_merge_dicts(merged, candidate)
    return merged


def _deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _derive_tool_adapter_entrypoints(
    spec: GitHubRemoteSource,
    *,
    adapter_config: dict[str, Any],
    readme_text: str,
) -> list[dict[str, Any]]:
    raw_entrypoints = adapter_config.get("entrypoints")
    normalized: list[dict[str, Any]] = []

    if isinstance(raw_entrypoints, list):
        for item in raw_entrypoints:
            entrypoint = _normalize_adapter_entrypoint(item)
            if entrypoint is not None:
                normalized.append(entrypoint)

    raw_adapter_targets = adapter_config.get("adapter_targets")
    if isinstance(raw_adapter_targets, list):
        for item in raw_adapter_targets:
            entrypoint = _normalize_adapter_entrypoint(item)
            if entrypoint is not None:
                normalized.append(entrypoint)

    if not normalized:
        for target in spec.adapter_targets:
            entrypoint = _normalize_adapter_entrypoint(target)
            if entrypoint is not None:
                normalized.append(entrypoint)

    if not normalized:
        hinted_tools = _extract_remote_llm_tool_specs(adapter_config, {}, {})
        for raw_tool in hinted_tools:
            entrypoint = _normalize_adapter_entrypoint(raw_tool.get("adapter_target") or raw_tool.get("target"))
            if entrypoint is not None:
                normalized.append(entrypoint)

    deduped: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for entrypoint in normalized:
        target = str(entrypoint.get("target") or "")
        if not target or target in seen_targets:
            continue
        seen_targets.add(target)
        deduped.append(entrypoint)

    if not deduped:
        raise RemotePackageImportError(
            f"远端 tool_adapter 源缺少 adapter target 声明: {spec.source_id} ({spec.owner}/{spec.repo})"
        )
    return deduped


def _normalize_adapter_entrypoint(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, str):
        target = raw.strip()
        if not target:
            return None
        if target == "render.native_pptx":
            raise RemotePackageImportError("render.native_pptx 已下线，远端原生渲染适配器不再支持导入")
        return {
            "kind": "adapter",
            "target": target,
            "description": _default_adapter_entrypoint_description(target),
        }

    if not isinstance(raw, dict):
        return None

    target = str(raw.get("target") or raw.get("adapter_target") or "").strip()
    if not target:
        return None
    if target == "render.native_pptx":
        raise RemotePackageImportError("render.native_pptx 已下线，远端原生渲染适配器不再支持导入")
    return {
        "kind": "adapter",
        "target": target,
        "description": str(raw.get("description") or _default_adapter_entrypoint_description(target)).strip(),
    }


def _default_adapter_entrypoint_description(target: str) -> str:
    if target == "deckspec.v1":
        return "读取或检查演示文稿的 canonical DeckSpec。"
    if target == "render.html_preview":
        return "将 canonical DeckSpec 渲染为 HTML 预览。"
    return f"Invoke adapter target {target}."


def _extract_remote_llm_tool_specs(
    adapter_config: dict[str, Any],
    plugin_json: dict[str, Any],
    marketplace_json: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = [
        adapter_config.get("llm_tools"),
        adapter_config.get("tools"),
        plugin_json.get("llm_tools") if isinstance(plugin_json, dict) else None,
        plugin_json.get("tools") if isinstance(plugin_json, dict) else None,
        marketplace_json.get("llm_tools") if isinstance(marketplace_json, dict) else None,
        marketplace_json.get("tools") if isinstance(marketplace_json, dict) else None,
        (marketplace_json.get("metadata") or {}).get("llm_tools") if isinstance(marketplace_json.get("metadata"), dict) else None,
        (marketplace_json.get("metadata") or {}).get("tools") if isinstance(marketplace_json.get("metadata"), dict) else None,
    ]
    for item in candidates:
        if isinstance(item, list):
            return [tool for tool in item if isinstance(tool, dict)]
    return []


def _derive_tool_adapter_llm_tools(
    *,
    package_id: str,
    display_name: str,
    description: str,
    entrypoints: list[dict[str, Any]],
    adapter_config: dict[str, Any],
    plugin_json: dict[str, Any],
    marketplace_json: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_tools = _extract_remote_llm_tool_specs(adapter_config, plugin_json, marketplace_json)
    if raw_tools:
        normalized = [
            item
            for item in (
                _normalize_remote_llm_tool(
                    raw_tool,
                    package_id=package_id,
                    entrypoints=entrypoints,
                )
                for raw_tool in raw_tools
            )
            if item is not None
        ]
        if normalized:
            return normalized

    return [
        {
            "name": _default_remote_tool_name(package_id, str(entrypoint.get("target") or "")),
            "description": _default_remote_tool_description(display_name, description, str(entrypoint.get("target") or "")),
            "parameters": _default_remote_tool_parameters(str(entrypoint.get("target") or "")),
            "adapter_target": str(entrypoint.get("target") or ""),
        }
        for entrypoint in entrypoints
    ]


def _normalize_remote_llm_tool(
    raw_tool: dict[str, Any],
    *,
    package_id: str,
    entrypoints: list[dict[str, Any]],
) -> dict[str, Any] | None:
    definition = raw_tool.get("definition") if isinstance(raw_tool.get("definition"), dict) else None
    if definition is not None:
        function_block = definition.get("function") if isinstance(definition.get("function"), dict) else {}
        tool_name = str(function_block.get("name") or raw_tool.get("name") or "").strip()
        tool_description = str(function_block.get("description") or raw_tool.get("description") or "").strip()
        parameters = function_block.get("parameters") if isinstance(function_block.get("parameters"), dict) else None
    else:
        tool_name = str(raw_tool.get("name") or "").strip()
        tool_description = str(raw_tool.get("description") or "").strip()
        parameters = raw_tool.get("parameters") if isinstance(raw_tool.get("parameters"), dict) else None

    if parameters is None and isinstance(raw_tool.get("input_schema"), dict):
        parameters = raw_tool.get("input_schema")
    if parameters is None and isinstance(raw_tool.get("schema"), dict):
        parameters = raw_tool.get("schema")

    adapter_target = str(raw_tool.get("adapter_target") or raw_tool.get("target") or "").strip()
    if not adapter_target and len(entrypoints) == 1:
        adapter_target = str(entrypoints[0].get("target") or "").strip()

    valid_targets = {str(entrypoint.get("target") or "") for entrypoint in entrypoints}
    if not adapter_target or adapter_target not in valid_targets:
        return None

    if not tool_name:
        tool_name = _default_remote_tool_name(package_id, adapter_target)
    if not tool_description:
        tool_description = _default_remote_tool_description(package_id, "", adapter_target)
    if parameters is None:
        parameters = _default_remote_tool_parameters(adapter_target)

    normalized = {
        "name": tool_name,
        "description": tool_description,
        "parameters": parameters,
        "adapter_target": adapter_target,
    }
    for key in ("expose_to_llm", "status", "runtime_metadata", "metadata"):
        if key in raw_tool:
            normalized[key] = raw_tool[key]
    return normalized


def _default_remote_tool_name(package_id: str, adapter_target: str) -> str:
    package_tail = re.sub(r"[^a-z0-9]+", "_", package_id.split(".")[-1].lower()).strip("_") or "adapter"
    target_alias = {
        "deckspec.v1": "deckspec",
        "render.html_preview": "html_preview",
    }.get(adapter_target, re.sub(r"[^a-z0-9]+", "_", adapter_target.lower()).strip("_"))
    return f"{package_tail}_{target_alias}"


def _default_remote_tool_description(display_name: str, description: str, adapter_target: str) -> str:
    if adapter_target == "deckspec.v1":
        return f"Inspect the canonical DeckSpec through {display_name or 'the adapter package'}."
    if adapter_target == "render.html_preview":
        return f"Render a presentation as HTML preview through {display_name or 'the adapter package'}."
    return description or f"Invoke adapter target {adapter_target}."


def _default_remote_tool_parameters(adapter_target: str) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "presentation_id": {
            "type": "string",
            "description": "The presentation ID to operate on.",
        }
    }
    required = ["presentation_id"]
    if adapter_target == "render.html_preview":
        properties["include_html"] = {
            "type": "boolean",
            "description": "When true, include the generated HTML string in the tool result.",
        }
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _derive_tool_adapter_tags(
    spec: GitHubRemoteSource,
    adapter_config: dict[str, Any],
    package_name: str,
    readme_text: str,
) -> list[str]:
    tags = ["github", "remote", "tool-adapter"]
    explicit_tags = adapter_config.get("tags")
    if isinstance(explicit_tags, list):
        tags.extend(str(tag) for tag in explicit_tags)
    else:
        tags.extend(part for part in re.split(r"[\s._-]+", package_name.lower()) if part)
    if "deckspec" in readme_text.lower() or "deckspec" in spec.package_id.lower():
        tags.append("deckspec")
    if "pptx" in readme_text.lower() or "pptx" in spec.package_id.lower():
        tags.append("pptx")
    if "html" in readme_text.lower() or "preview" in readme_text.lower():
        tags.append("preview")
    seen: set[str] = set()
    return [tag for tag in tags if not (tag.lower() in seen or seen.add(tag.lower()))]


def _derive_tool_adapter_capabilities(entrypoints: list[dict[str, Any]]) -> list[str]:
    capabilities = {"tool.dynamic_llm"}
    target_map = {
        "deckspec.v1": "deckspec.inspect",
        "render.html_preview": "preview.render.html",
    }
    for entrypoint in entrypoints:
        target = str(entrypoint.get("target") or "")
        if target in target_map:
            capabilities.add(target_map[target])
    return sorted(capabilities)


def _derive_tool_adapter_permissions(entrypoints: list[dict[str, Any]]) -> list[dict[str, str]]:
    permissions: dict[str, str] = {}
    for entrypoint in entrypoints:
        target = str(entrypoint.get("target") or "")
        if target == "deckspec.v1":
            permissions.setdefault("registry.read", "读取 DeckSpec 契约与平台元数据以解析 canonical 表示。")
        elif target == "render.html_preview":
            permissions.setdefault("preview.render", "生成 HTML 预览内容。")
            permissions.setdefault("asset.write", "保存 HTML 预览产物到平台资产目录。")
    return [{"name": name, "rationale": rationale} for name, rationale in permissions.items()]


def _derive_tool_adapter_dependencies(entrypoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dependencies: dict[str, dict[str, Any]] = {
        "official.deckspec-contract": {
            "package_id": "official.deckspec-contract",
            "version_constraint": ">=0.2.0",
        }
    }
    for entrypoint in entrypoints:
        target = str(entrypoint.get("target") or "")
        if target == "render.html_preview":
            dependencies.setdefault(
                "official.html-preview-renderer",
                {"package_id": "official.html-preview-renderer", "version_constraint": ">=0.2.0", "optional": True},
            )
    return list(dependencies.values())