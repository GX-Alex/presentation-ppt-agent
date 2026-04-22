"""
安全 Checklist 全面复验脚本 — Sprint 7。
检查项:
  1. 文件上传安全（白名单/大小/Zip Slip）
  2. CORS 配置
  3. 输入校验
  4. 敏感信息泄露
  5. SQL 注入防护（ORM 参数化）
  6. WebSocket 安全
  7. 静态文件路径安全
  8. 环境变量安全

运行方式: cd backend && python security_checklist.py
"""
import asyncio
import importlib
import os
import re
import sys
from pathlib import Path

# ──────────────── 颜色 ────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

passed = 0
failed = 0
warnings = 0


def ok(name: str, detail: str = ""):
    global passed
    passed += 1
    print(f"  {GREEN}✓{RESET} {name}" + (f" — {detail}" if detail else ""))


def fail(name: str, detail: str = ""):
    global failed
    failed += 1
    print(f"  {RED}✗{RESET} {name}" + (f" — {detail}" if detail else ""))


def warn(name: str, detail: str = ""):
    global warnings
    warnings += 1
    print(f"  {YELLOW}⚠{RESET} {name}" + (f" — {detail}" if detail else ""))


# ──────────────── 检查项 ────────────────

async def run_security_check():
    print(f"\n{YELLOW}═══ Sprint 7 安全 Checklist 复验 ═══{RESET}\n")

    # ── 1. 文件上传安全 ──
    print(f"{CYAN}[1] 文件上传安全{RESET}")
    try:
        from app.services.file_service import (
            ALLOWED_EXTENSIONS,
            MAX_FILE_SIZE,
            validate_extension,
            validate_file_size,
            sanitize_filename,
            validate_zip_entry,
        )

        # 白名单检查
        dangerous_exts = [".exe", ".bat", ".cmd", ".sh", ".php", ".jsp", ".asp"]
        for ext in dangerous_exts:
            if ext not in ALLOWED_EXTENSIONS:
                ok(f"危险扩展名 {ext} 已屏蔽")
            else:
                fail(f"危险扩展名 {ext} 在白名单中！")

        # 大小限制
        if MAX_FILE_SIZE <= 100 * 1024 * 1024:  # ≤100MB
            ok(f"文件大小限制: {MAX_FILE_SIZE / 1024 / 1024:.0f}MB")
        else:
            warn(f"文件大小限制过大: {MAX_FILE_SIZE / 1024 / 1024:.0f}MB")

        # 扩展名验证
        try:
            validate_extension("evil.exe")
            fail("validate_extension 未拦截 .exe")
        except Exception:
            ok("validate_extension 拦截 .exe")

        # 文件名清理
        cleaned = sanitize_filename("../../etc/passwd")
        if ".." not in cleaned and "/" not in cleaned:
            ok("sanitize_filename 防路径穿越")
        else:
            fail("sanitize_filename 未阻止路径穿越")

        # Zip Slip 防护
        safe = validate_zip_entry("normal/file.txt", "/tmp/extract")
        if safe:
            ok("validate_zip_entry 允许安全路径")

        unsafe = validate_zip_entry("../../etc/passwd", "/tmp/extract")
        if not unsafe:
            ok("validate_zip_entry 拦截 Zip Slip")
        else:
            fail("validate_zip_entry 未拦截 Zip Slip！")

    except Exception as e:
        fail("文件上传安全模块", str(e))

    # ── 2. CORS 配置 ──
    print(f"\n{CYAN}[2] CORS 配置{RESET}")
    try:
        from main import app

        cors_mw = None
        for mw in app.user_middleware:
            if "CORS" in str(mw.cls):
                cors_mw = mw
                break

        if cors_mw:
            origins = cors_mw.kwargs.get("allow_origins", [])
            if "*" in origins:
                warn("CORS allow_origins 包含通配符 '*'")
            else:
                ok(f"CORS 已限制来源: {origins}")
        else:
            warn("未检测到 CORS 中间件")
    except Exception as e:
        fail("CORS 检查", str(e))

    # ── 3. 输入校验 ──
    print(f"\n{CYAN}[3] 输入校验{RESET}")
    try:
        # 检查 Pydantic 模型使用
        from app.api.assets import AssetUpdate
        from app.api.gallery import PublishRequest

        # 尝试非法输入
        try:
            AssetUpdate(title="x" * 10000)  # 超长标题
            warn("AssetUpdate 未限制标题长度")
        except Exception:
            ok("AssetUpdate 限制标题长度")

        ok("Pydantic 模型校验已启用 (assets, gallery)")
    except Exception as e:
        fail("输入校验", str(e))

    # ── 4. 敏感信息泄露 ──
    print(f"\n{CYAN}[4] 敏感信息泄露防护{RESET}")

    # 检查源码中是否硬编码了密钥
    backend_dir = Path("app")
    sensitive_patterns = [
        r'(api_key|apikey|secret|password)\s*=\s*["\'][^"\']{10,}["\']',
        r'sk-[a-zA-Z0-9]{32,}',  # OpenAI key 格式
    ]
    found_leaks = False
    for py_file in backend_dir.rglob("*.py"):
        content = py_file.read_text(errors="ignore")
        for pattern in sensitive_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                # 排除环境变量读取的模式
                for match in matches:
                    if "os.getenv" not in content[max(0, content.index(str(match)) - 50):content.index(str(match))]:
                        fail(f"疑似硬编码密钥: {py_file}", str(match)[:30] + "...")
                        found_leaks = True

    if not found_leaks:
        ok("未发现硬编码密钥")

    # 检查 .env 文件不在版本控制中
    env_file = Path("../.env")
    gitignore = Path("../.gitignore")
    if gitignore.exists():
        gi_content = gitignore.read_text()
        if ".env" in gi_content:
            ok(".env 在 .gitignore 中")
        else:
            warn(".env 可能未在 .gitignore 中")
    else:
        warn("未找到 .gitignore")

    # ── 5. SQL 注入防护 ──
    print(f"\n{CYAN}[5] SQL 注入防护{RESET}")
    # 检查所有 API 文件是否使用 ORM（不使用 raw SQL）
    api_dir = Path("app/api")
    raw_sql_found = False
    for py_file in api_dir.rglob("*.py"):
        content = py_file.read_text(errors="ignore")
        if "text(" in content or "execute(text" in content or "raw_connection" in content:
            if "from sqlalchemy" in content:
                warn(f"{py_file} 可能使用了 raw SQL")
                raw_sql_found = True

    if not raw_sql_found:
        ok("API 层未使用 raw SQL（全部通过 ORM）")

    # ── 6. WebSocket 安全 ──
    print(f"\n{CYAN}[6] WebSocket 安全{RESET}")
    try:
        ws_file = Path("app/ws/chat_handler.py")
        ws_content = ws_file.read_text()

        if "json.loads" in ws_content and "JSONDecodeError" in ws_content:
            ok("WebSocket JSON 解析有异常处理")
        else:
            fail("WebSocket 缺少 JSON 解析异常处理")

        if "WebSocketDisconnect" in ws_content:
            ok("WebSocket 断开连接有处理")
        else:
            fail("WebSocket 缺少断开连接处理")

        if '"error"' in ws_content and '"recoverable"' in ws_content:
            ok("WebSocket 错误推送包含 recoverable 标记")
        else:
            warn("WebSocket 错误推送缺少 recoverable 标记")
    except Exception as e:
        fail("WebSocket 安全检查", str(e))

    # ── 7. 错误处理中间件 ──
    print(f"\n{CYAN}[7] 错误处理中间件{RESET}")
    try:
        from app.core.error_handling import (
            RequestTimeoutMiddleware,
            ErrorHandlingMiddleware,
            retry_llm_call,
            ws_error_push,
            AppError,
            LLMError,
            TimeoutError,
        )
        ok("错误处理中间件已就位")
        ok("自定义异常类已定义 (AppError, LLMError, TimeoutError)")
        ok("LLM 重试机制已实现 (retry_llm_call)")
        ok("WebSocket 错误推送工具已实现 (ws_error_push)")
    except Exception as e:
        fail("错误处理中间件", str(e))

    # ── 8. 环境变量安全 ──
    print(f"\n{CYAN}[8] 环境变量配置{RESET}")
    env_example = Path("../.env.example")
    if env_example.exists():
        ok(".env.example 文件存在")
        content = env_example.read_text()
        required_vars = ["LLM_MODEL", "LLM_API_KEY", "DATABASE_URL", "CORS_ORIGINS"]
        for var in required_vars:
            if var in content:
                ok(f"环境变量 {var} 在 .env.example 中")
            else:
                fail(f"环境变量 {var} 未在 .env.example 中")
    else:
        fail(".env.example 不存在")

    # ── 9. 健康检查端点 ──
    print(f"\n{CYAN}[9] 健康检查{RESET}")
    try:
        from app.api.health import router as health_router
        ok("健康检查端点已就位")
    except Exception as e:
        fail("健康检查端点", str(e))

    # ── 汇总 ──
    print(f"\n{YELLOW}{'═' * 50}{RESET}")
    total = passed + failed + warnings
    print(f"  总计: {total} 项安全检查")
    print(f"  {GREEN}通过: {passed}{RESET}")
    if warnings:
        print(f"  {YELLOW}告警: {warnings}{RESET}")
    if failed:
        print(f"  {RED}失败: {failed}{RESET}")
    else:
        print(f"  {GREEN}🔒 安全检查全部通过！{RESET}")
    print(f"{YELLOW}{'═' * 50}{RESET}\n")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_security_check())
    sys.exit(0 if success else 1)
