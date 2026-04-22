"""
Sprint 7 验证测试 — 错误处理 + 前端收尾 + 性能 + 安全 + Docker + README。
运行: cd backend && python quick_test_sprint7.py
"""
import ast
import importlib
import json
import os
import re
import sys
import time

# ────────────── 测试结果跟踪 ──────────────
_passed = 0
_failed = 0
_errors: list[str] = []


def _ok(name: str):
    global _passed
    _passed += 1
    print(f"  ✅ {name}")


def _fail(name: str, reason: str):
    global _failed
    _failed += 1
    _errors.append(f"{name}: {reason}")
    print(f"  ❌ {name} — {reason}")


# ════════════════════════════════════════════════════
#  1. 错误处理模块 — 自定义异常
# ════════════════════════════════════════════════════
def test_custom_exceptions():
    print("\n🔧 1. 错误处理 — 自定义异常")
    from app.core.error_handling import AppError, TimeoutError, RateLimitError, LLMError

    # 1a. AppError 基类
    try:
        err = AppError("测试错误", status_code=400, detail="详情")
        assert err.message == "测试错误"
        assert err.status_code == 400
        assert err.detail == "详情"
        _ok("AppError 基类字段正确")
    except Exception as e:
        _fail("AppError 基类", str(e))

    # 1b. TimeoutError
    try:
        err = TimeoutError(timeout=60)
        assert err.status_code == 504
        assert err.timeout == 60
        _ok("TimeoutError 状态码 504")
    except Exception as e:
        _fail("TimeoutError", str(e))

    # 1c. RateLimitError
    try:
        err = RateLimitError()
        assert err.status_code == 429
        _ok("RateLimitError 状态码 429")
    except Exception as e:
        _fail("RateLimitError", str(e))

    # 1d. LLMError
    try:
        err = LLMError(detail="连接超时")
        assert err.status_code == 502
        assert err.detail == "连接超时"
        _ok("LLMError 状态码 502 + detail")
    except Exception as e:
        _fail("LLMError", str(e))

    # 1e. 继承关系
    try:
        assert issubclass(TimeoutError, AppError)
        assert issubclass(RateLimitError, AppError)
        assert issubclass(LLMError, AppError)
        _ok("异常继承关系正确")
    except Exception as e:
        _fail("异常继承关系", str(e))


# ════════════════════════════════════════════════════
#  2. 错误处理模块 — 中间件类存在
# ════════════════════════════════════════════════════
def test_middleware_classes():
    print("\n🔧 2. 错误处理 — 中间件类")
    from app.core.error_handling import RequestTimeoutMiddleware, ErrorHandlingMiddleware

    # 2a. RequestTimeoutMiddleware 存在
    try:
        assert RequestTimeoutMiddleware is not None
        _ok("RequestTimeoutMiddleware 已定义")
    except Exception as e:
        _fail("RequestTimeoutMiddleware", str(e))

    # 2b. ErrorHandlingMiddleware 存在
    try:
        assert ErrorHandlingMiddleware is not None
        _ok("ErrorHandlingMiddleware 已定义")
    except Exception as e:
        _fail("ErrorHandlingMiddleware", str(e))


# ════════════════════════════════════════════════════
#  3. 错误处理模块 — 重试 + WS 错误推送
# ════════════════════════════════════════════════════
def test_retry_and_ws_push():
    print("\n🔧 3. 错误处理 — 重试 + WebSocket 错误推送")
    import asyncio
    from app.core.error_handling import retry_llm_call, ws_error_push, LLMError

    # 3a. retry_llm_call — 成功场景
    try:
        call_count = 0

        async def succeed_on_second():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("模拟失败")
            return "成功"

        result = asyncio.get_event_loop().run_until_complete(
            retry_llm_call(succeed_on_second, max_retries=3, base_delay=0.01)
        )
        assert result == "成功"
        assert call_count == 2
        _ok("retry_llm_call 第二次成功")
    except Exception as e:
        _fail("retry_llm_call 成功场景", str(e))

    # 3b. retry_llm_call — 全部失败
    try:
        async def always_fail():
            raise Exception("永远失败")

        try:
            asyncio.get_event_loop().run_until_complete(
                retry_llm_call(always_fail, max_retries=2, base_delay=0.01)
            )
            _fail("retry_llm_call 全部失败", "应该抛出 LLMError")
        except LLMError:
            _ok("retry_llm_call 耗尽重试后抛出 LLMError")
    except Exception as e:
        _fail("retry_llm_call 全部失败", str(e))

    # 3c. ws_error_push — 结构化推送
    try:
        received = []

        async def mock_send(msg):
            received.append(msg)

        asyncio.get_event_loop().run_until_complete(
            ws_error_push(mock_send, LLMError("模型不可用"), recoverable=True, context="生成幻灯片")
        )
        assert len(received) == 1
        msg = received[0]
        assert msg["type"] == "error"
        assert msg["recoverable"] is True
        assert "error_type" in msg
        assert "context" in msg
        _ok("ws_error_push 推送结构化错误消息")
    except Exception as e:
        _fail("ws_error_push", str(e))


# ════════════════════════════════════════════════════
#  4. main.py 中间件注册
# ════════════════════════════════════════════════════
def test_main_middleware_registration():
    print("\n🔧 4. main.py — 中间件注册验证")
    main_path = os.path.join(os.path.dirname(__file__), "main.py")

    try:
        with open(main_path, "r") as f:
            content = f.read()

        # 4a. 导入 error_handling
        assert "from app.core.error_handling import" in content
        _ok("main.py 导入 error_handling 模块")

        # 4b. 注册 ErrorHandlingMiddleware
        assert "ErrorHandlingMiddleware" in content
        assert "app.add_middleware(ErrorHandlingMiddleware)" in content
        _ok("main.py 注册 ErrorHandlingMiddleware")

        # 4c. 注册 RequestTimeoutMiddleware
        assert "RequestTimeoutMiddleware" in content
        assert "app.add_middleware(RequestTimeoutMiddleware" in content
        _ok("main.py 注册 RequestTimeoutMiddleware")
    except Exception as e:
        _fail("main.py 中间件注册", str(e))


# ════════════════════════════════════════════════════
#  5. i18n 国际化模块
# ════════════════════════════════════════════════════
def test_i18n_module():
    print("\n🔧 5. i18n — 国际化壳子")
    i18n_path = os.path.join(
        os.path.dirname(__file__), "..", "frontend", "src", "lib", "i18n.ts"
    )

    try:
        with open(i18n_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        _fail("i18n.ts 文件存在", "文件不存在")
        return

    # 5a. 文件存在
    _ok("i18n.ts 文件存在")

    # 5b. 包含翻译函数
    if "function t(" in content or "export function t" in content or "const t" in content:
        _ok("包含翻译函数 t()")
    else:
        _fail("翻译函数 t()", "未找到")

    # 5c. 包含中文语言包
    if "zhCN" in content or "zh-CN" in content or "zh_CN" in content:
        _ok("包含中文语言包")
    else:
        _fail("中文语言包", "未找到")

    # 5d. 导航相关翻译键
    nav_keys = ["newTask", "assets", "gallery", "settings"]
    found = sum(1 for k in nav_keys if k in content)
    if found >= 3:
        _ok(f"导航翻译键 ({found}/{len(nav_keys)})")
    else:
        _fail("导航翻译键", f"仅找到 {found}/{len(nav_keys)}")

    # 5e. 多语言扩展接口
    if "setLocale" in content or "getLocale" in content or "locale" in content:
        _ok("预留多语言扩展接口")
    else:
        _fail("多语言扩展接口", "未找到 setLocale/getLocale")


# ════════════════════════════════════════════════════
#  6. 前端 — 响应式布局
# ════════════════════════════════════════════════════
def test_responsive_layout():
    print("\n🔧 6. 前端 — 响应式布局")

    # 6a. Sidebar 响应式
    sidebar_path = os.path.join(
        os.path.dirname(__file__), "..", "frontend", "src", "components", "layout", "Sidebar.tsx"
    )
    try:
        with open(sidebar_path, "r") as f:
            sidebar_content = f.read()

        # 移动端菜单
        if "mobileOpen" in sidebar_content or "mobile" in sidebar_content.lower():
            _ok("Sidebar 包含移动端适配")
        else:
            _fail("Sidebar 移动端适配", "未找到 mobileOpen 状态")

        # 折叠功能
        if "collapsed" in sidebar_content:
            _ok("Sidebar 包含折叠功能")
        else:
            _fail("Sidebar 折叠功能", "未找到 collapsed 状态")

        # Lucide 图标
        if "lucide-react" in sidebar_content:
            _ok("Sidebar 使用 Lucide 图标")
        else:
            _fail("Sidebar Lucide 图标", "未找到 lucide-react 导入")

        # 任务历史
        if "tasks" in sidebar_content and ("TaskSummary" in sidebar_content or "task" in sidebar_content):
            _ok("Sidebar 包含任务历史列表")
        else:
            _fail("Sidebar 任务历史", "未找到任务列表代码")
    except FileNotFoundError:
        _fail("Sidebar.tsx 文件存在", "文件不存在")

    # 6b. layout.tsx viewport
    layout_path = os.path.join(
        os.path.dirname(__file__), "..", "frontend", "src", "app", "layout.tsx"
    )
    try:
        with open(layout_path, "r") as f:
            layout_content = f.read()

        if "viewport" in layout_content.lower() and "device-width" in layout_content:
            _ok("layout.tsx 配置 viewport")
        else:
            _fail("layout.tsx viewport", "未找到 viewport 配置")

        if 'lang="zh-CN"' in layout_content:
            _ok("layout.tsx 设置 zh-CN 语言")
        else:
            _fail("layout.tsx zh-CN", "未找到 lang='zh-CN'")
    except FileNotFoundError:
        _fail("layout.tsx 文件存在", "文件不存在")


# ════════════════════════════════════════════════════
#  7. Docker Compose 生产配置
# ════════════════════════════════════════════════════
def test_docker_compose():
    print("\n🔧 7. Docker Compose — 生产配置")
    dc_path = os.path.join(os.path.dirname(__file__), "..", "docker-compose.yml")

    try:
        with open(dc_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        _fail("docker-compose.yml 文件存在", "文件不存在")
        return

    _ok("docker-compose.yml 文件存在")

    # 7a. 参数化端口
    if "BACKEND_PORT" in content:
        _ok("后端端口参数化 (BACKEND_PORT)")
    else:
        _fail("后端端口参数化", "未找到 BACKEND_PORT")

    if "FRONTEND_PORT" in content:
        _ok("前端端口参数化 (FRONTEND_PORT)")
    else:
        _fail("前端端口参数化", "未找到 FRONTEND_PORT")

    # 7b. 环境变量透传
    if "PLAYWRIGHT_MAX_PAGES" in content:
        _ok("PLAYWRIGHT_MAX_PAGES 环境变量")
    else:
        _fail("PLAYWRIGHT_MAX_PAGES", "未找到")

    if "MODEL_CONTEXT_WINDOW" in content:
        _ok("MODEL_CONTEXT_WINDOW 环境变量")
    else:
        _fail("MODEL_CONTEXT_WINDOW", "未找到")

    # 7c. 健康检查
    if "healthcheck" in content:
        _ok("包含 healthcheck 配置")
    else:
        _fail("healthcheck", "未找到")

    # 7d. 内存限制
    if "memory" in content:
        _ok("包含内存限制配置")
    else:
        _fail("内存限制", "未找到 memory 配置")

    # 7e. 数据卷
    if "volumes" in content:
        _ok("包含数据卷挂载")
    else:
        _fail("数据卷", "未找到 volumes 配置")


# ════════════════════════════════════════════════════
#  8. .env.example 完整性
# ════════════════════════════════════════════════════
def test_env_example():
    print("\n🔧 8. .env.example — 环境变量模板")
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env.example")

    try:
        with open(env_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        _fail(".env.example 文件存在", "文件不存在")
        return

    _ok(".env.example 文件存在")

    required_vars = [
        "LLM_API_KEY",
        "LLM_MODEL",
        "DATABASE_URL",
        "CORS_ORIGINS",
        "PLAYWRIGHT_MAX_PAGES",
        "MODEL_CONTEXT_WINDOW",
        "BACKEND_PORT",
        "FRONTEND_PORT",
    ]

    for var in required_vars:
        if var in content:
            _ok(f"包含 {var}")
        else:
            _fail(f"包含 {var}", "未找到")

    # 包含中文注释
    if re.search(r"[\u4e00-\u9fff]", content):
        _ok(".env.example 包含中文注释")
    else:
        _fail(".env.example 中文注释", "未找到中文字符")


# ════════════════════════════════════════════════════
#  9. README 文档
# ════════════════════════════════════════════════════
def test_readme():
    print("\n🔧 9. README — 项目文档")
    readme_path = os.path.join(os.path.dirname(__file__), "..", "README.md")

    try:
        with open(readme_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        _fail("README.md 文件存在", "文件不存在")
        return

    _ok("README.md 文件存在")

    # 内容完整性检查
    sections = [
        ("项目概述", "项目概述|产品定位|General Agent"),
        ("技术栈", "技术栈|Tech Stack"),
        ("快速启动", "快速启动|Quick Start|docker compose"),
        ("本地开发", "本地开发|Development"),
        ("项目结构", "项目结构|Project Structure"),
        ("API 接口", "API|接口|endpoint"),
        ("环境变量", "环境变量|Environment"),
    ]

    for name, pattern in sections:
        if re.search(pattern, content, re.IGNORECASE):
            _ok(f"README 包含「{name}」章节")
        else:
            _fail(f"README「{name}」", "未找到")


# ════════════════════════════════════════════════════
#  10. 性能 + 安全脚本存在
# ════════════════════════════════════════════════════
def test_scripts_exist():
    print("\n🔧 10. 验证脚本 — 文件存在")
    base = os.path.dirname(__file__)

    scripts = [
        ("perf_baseline.py", "性能基线脚本"),
        ("security_checklist.py", "安全 checklist 脚本"),
    ]

    for filename, desc in scripts:
        path = os.path.join(base, filename)
        if os.path.exists(path):
            _ok(f"{desc} ({filename})")
        else:
            _fail(desc, f"{filename} 不存在")


# ════════════════════════════════════════════════════
#  11. 后端 Dockerfile 完善
# ════════════════════════════════════════════════════
def test_backend_dockerfile():
    print("\n🔧 11. 后端 Dockerfile — 生产配置")
    dockerfile_path = os.path.join(os.path.dirname(__file__), "Dockerfile")

    try:
        with open(dockerfile_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        _fail("Dockerfile 文件存在", "文件不存在")
        return

    _ok("Dockerfile 文件存在")

    # Playwright 安装
    if "playwright install" in content:
        _ok("Dockerfile 包含 Playwright 安装")
    else:
        _fail("Dockerfile Playwright", "未找到 playwright install")

    # HEALTHCHECK
    if "HEALTHCHECK" in content:
        _ok("Dockerfile 包含 HEALTHCHECK")
    else:
        _fail("Dockerfile HEALTHCHECK", "未找到")

    # 数据目录
    if "data/uploads" in content and "data/exports" in content:
        _ok("Dockerfile 创建数据目录")
    else:
        _fail("Dockerfile 数据目录", "未找到 data/ 目录创建")


# ════════════════════════════════════════════════════
#  12. 模块导入性能
# ════════════════════════════════════════════════════
def test_import_performance():
    print("\n🔧 12. 模块导入 — 性能检查")

    modules = [
        ("app.core.error_handling", "错误处理模块"),
        ("app.core.tool_dispatch", "Tool 分发模块"),
        ("app.models.tables", "ORM 模型"),
    ]

    for mod_name, desc in modules:
        start = time.time()
        try:
            importlib.import_module(mod_name)
            elapsed = (time.time() - start) * 1000
            if elapsed < 500:
                _ok(f"{desc} 导入耗时 {elapsed:.0f}ms < 500ms")
            else:
                _fail(f"{desc} 导入", f"耗时 {elapsed:.0f}ms 超过 500ms")
        except Exception as e:
            _fail(f"{desc} 导入", str(e))


# ══════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("Sprint 7 验证测试 — 错误处理 + 前端收尾 + 工程质量")
    print("=" * 60)

    test_custom_exceptions()
    test_middleware_classes()
    test_retry_and_ws_push()
    test_main_middleware_registration()
    test_i18n_module()
    test_responsive_layout()
    test_docker_compose()
    test_env_example()
    test_readme()
    test_scripts_exist()
    test_backend_dockerfile()
    test_import_performance()

    # ── 汇总 ──
    print("\n" + "=" * 60)
    total = _passed + _failed
    print(f"  总计: {total}  ✅ 通过: {_passed}  ❌ 失败: {_failed}")
    if _errors:
        print("\n  失败详情:")
        for e in _errors:
            print(f"    • {e}")
    print("=" * 60)

    sys.exit(0 if _failed == 0 else 1)
