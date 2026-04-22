"""
fetch_url 工具 — 抓取 URL 页面内容。
使用 trafilatura 提取正文，httpx 发送请求。
内置 SSRF 防护：阻止访问私有 IP 地址。
"""
import ipaddress
import logging
import os
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ──────────────── Tool 定义（OpenAI function-calling 格式）────────────────
TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "fetch_url",
        "description": (
            "抓取指定 URL 的网页内容，自动提取正文文本。"
            "适用于从用户提供的链接获取文章、文档、博客等内容。"
            "包含安全防护，禁止访问内网地址。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要抓取的网页 URL（必须是 http:// 或 https://）",
                },
                "extract_mode": {
                    "type": "string",
                    "description": "提取模式: 'article'（正文提取，默认）| 'raw'（原始 HTML）",
                    "enum": ["article", "raw"],
                    "default": "article",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "最大返回字符数（默认 30000）",
                    "default": 30000,
                },
            },
            "required": ["url"],
        },
    },
}

# HTTP 请求超时（秒）
REQUEST_TIMEOUT = 20.0

# 最大下载大小（5MB）
MAX_DOWNLOAD_SIZE = 5 * 1024 * 1024

# User-Agent
USER_AGENT = "GeneralAgent/1.0 (Content Fetcher)"


# ──────────────────── SSRF 防护 ────────────────────

# RFC 1918 + 其他私有/回环/链路本地地址
BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),        # Class A 私有
    ipaddress.ip_network("172.16.0.0/12"),      # Class B 私有
    ipaddress.ip_network("192.168.0.0/16"),     # Class C 私有
    ipaddress.ip_network("127.0.0.0/8"),        # 回环地址
    ipaddress.ip_network("169.254.0.0/16"),     # 链路本地
    ipaddress.ip_network("0.0.0.0/8"),          # 本地网络
    ipaddress.ip_network("100.64.0.0/10"),      # CGN 共享地址
    ipaddress.ip_network("198.18.0.0/15"),      # 基准测试
    ipaddress.ip_network("::1/128"),            # IPv6 回环
    ipaddress.ip_network("fc00::/7"),           # IPv6 唯一本地
    ipaddress.ip_network("fe80::/10"),          # IPv6 链路本地
]

# 屏蔽的域名
BLOCKED_HOSTNAMES = {
    "localhost", "localhost.localdomain",
    "metadata.google.internal",  # GCP 元数据
    "169.254.169.254",           # AWS/GCP/Azure 元数据
}


class SSRFError(Exception):
    """SSRF 攻击检测异常。"""
    pass


def check_ssrf(url: str) -> None:
    """
    检查 URL 是否存在 SSRF 风险。

    验证项:
    1. URL scheme 必须是 http/https
    2. 主机名不在屏蔽列表
    3. DNS 解析后的 IP 不在私有/回环网段

    Raises:
        SSRFError: 检测到 SSRF 风险
    """
    parsed = urlparse(url)

    # 1. 协议检查
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"不支持的协议: {parsed.scheme}，仅允许 http/https")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("URL 缺少主机名")

    # 2. 域名黑名单检查
    hostname_lower = hostname.lower()
    if hostname_lower in BLOCKED_HOSTNAMES:
        raise SSRFError(f"禁止访问: {hostname}")

    # 3. DNS 解析并检查 IP
    try:
        addr_infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise SSRFError(f"域名解析失败: {hostname}")

    for family, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        for network in BLOCKED_NETWORKS:
            if ip in network:
                raise SSRFError(
                    f"SSRF 防护: {hostname} 解析到私有地址 {ip_str} "
                    f"(网段 {network})，禁止访问"
                )


# ──────────────── Tool 执行入口 ────────────────

async def execute(params: dict[str, Any]) -> dict[str, Any]:
    """
    抓取 URL 内容。

    Args:
        params: {
            "url": str,
            "extract_mode": str (可选, 默认 "article"),
            "max_chars": int (可选, 默认 30000),
        }

    Returns:
        {
            "url": str,
            "title": str | None,
            "content": str,
            "char_count": int,
            "truncated": bool,
            "extract_mode": str,
        }
    """
    url = params.get("url", "").strip()
    extract_mode = params.get("extract_mode", "article")
    max_chars = params.get("max_chars", 30000)

    if not url:
        return {"error": "URL 不能为空"}

    # 补全协议
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # SSRF 安全检查
    try:
        check_ssrf(url)
    except SSRFError as e:
        logger.warning(f"[fetch_url] SSRF 拦截: {url} — {e}")
        return {"error": str(e)}

    # 发送 HTTP 请求
    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            max_redirects=5,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            # 大小检查
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_DOWNLOAD_SIZE:
                return {"error": f"页面过大: {int(content_length)} 字节，超过 {MAX_DOWNLOAD_SIZE} 字节限制"}

            raw_html = response.text

            if len(raw_html) > MAX_DOWNLOAD_SIZE:
                return {"error": f"页面内容过大: {len(raw_html)} 字符"}

    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {url}"}
    except httpx.TimeoutException:
        return {"error": f"请求超时（{REQUEST_TIMEOUT}秒）: {url}"}
    except Exception as e:
        logger.exception(f"[fetch_url] 请求失败: {url}")
        return {"error": f"请求失败: {str(e)}"}

    # 内容提取
    title = None
    content = raw_html

    if extract_mode == "article":
        try:
            import trafilatura

            downloaded = trafilatura.extract(
                raw_html,
                include_comments=False,
                include_tables=True,
                output_format="txt",
            )

            if downloaded:
                content = downloaded

            # 提取标题
            meta = trafilatura.extract(
                raw_html,
                output_format="xml",
                include_comments=False,
            )
            if meta:
                import re
                title_match = re.search(r'<title>(.*?)</title>', meta, re.DOTALL)
                if title_match:
                    title = title_match.group(1).strip()

        except Exception as e:
            logger.warning(f"[fetch_url] trafilatura 提取失败，使用原始 HTML: {e}")
            # fallback: 简单去标签
            import re
            content = re.sub(r'<[^>]+>', '', raw_html)
            content = re.sub(r'\s+', ' ', content).strip()

    # 截断
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars]
        content += f"\n\n... [内容已截断，共 {len(content)} 字符]"

    logger.info(f"[fetch_url] 抓取成功: {url} ({len(content)} 字符)")

    return {
        "url": url,
        "title": title,
        "content": content,
        "char_count": len(content),
        "truncated": truncated,
        "extract_mode": extract_mode,
    }
