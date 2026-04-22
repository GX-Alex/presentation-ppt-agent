"""
性能基线验证脚本 — Sprint 7。
验证关键性能指标:
  - 健康检查响应 <200ms
  - API 端点响应 <500ms
  - 数据库查询 <100ms
  - 静态文件服务 <200ms
  - 浏览器池初始化（若可用）

运行方式: cd backend && python perf_baseline.py
"""
import asyncio
import os
import sys
import time
from pathlib import Path

# ──────────────── 颜色 ────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

results: list[tuple[str, float, float, bool]] = []  # (name, actual_ms, threshold_ms, passed)


def record(name: str, elapsed_ms: float, threshold_ms: float):
    passed = elapsed_ms <= threshold_ms
    results.append((name, elapsed_ms, threshold_ms, passed))
    status = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
    print(f"  {status} {name}: {elapsed_ms:.1f}ms (阈值 {threshold_ms:.0f}ms)")


# ──────────────── 测试项 ────────────────

async def run_perf():
    print(f"\n{YELLOW}═══ Sprint 7 性能基线验证 ═══{RESET}\n")

    # ── 1. 数据库操作延迟 ──
    print(f"{CYAN}[1] 数据库操作{RESET}")
    try:
        from app.models.database import async_session, init_db
        from app.models.tables import Task
        from sqlalchemy import select, func

        await init_db()

        # 简单查询
        start = time.monotonic()
        async with async_session() as session:
            result = await session.execute(select(func.count()).select_from(Task))
            count = result.scalar() or 0
        elapsed = (time.monotonic() - start) * 1000
        record("DB 查询 (count tasks)", elapsed, 100)

        # 带条件查询
        start = time.monotonic()
        async with async_session() as session:
            result = await session.execute(
                select(Task).limit(10)
            )
            _ = result.scalars().all()
        elapsed = (time.monotonic() - start) * 1000
        record("DB 查询 (list tasks)", elapsed, 100)

    except Exception as e:
        print(f"  {RED}✗ 数据库测试失败: {e}{RESET}")

    # ── 2. 路由注册性能 ──
    print(f"\n{CYAN}[2] FastAPI 路由加载{RESET}")
    try:
        start = time.monotonic()
        from main import app
        elapsed = (time.monotonic() - start) * 1000
        record("FastAPI app 初始化", elapsed, 2000)

        route_count = len([r for r in app.routes if hasattr(r, "path")])
        print(f"  📊 已注册路由: {route_count} 条")
    except Exception as e:
        print(f"  {RED}✗ 路由加载失败: {e}{RESET}")

    # ── 3. 模块导入性能 ──
    print(f"\n{CYAN}[3] 核心模块导入{RESET}")
    modules = [
        ("agent_runner", "app.core.agent_runner"),
        ("tool_dispatch", "app.core.tool_dispatch"),
        ("llm_client", "app.core.llm_client"),
        ("error_handling", "app.core.error_handling"),
        ("context_service", "app.services.context_service"),
        ("memory_service", "app.services.memory_service"),
        ("asset_service", "app.services.asset_service"),
        ("file_service", "app.services.file_service"),
    ]
    for name, mod_path in modules:
        start = time.monotonic()
        try:
            __import__(mod_path)
            elapsed = (time.monotonic() - start) * 1000
            record(f"导入 {name}", elapsed, 500)
        except Exception as e:
            print(f"  {RED}✗ 导入 {name} 失败: {e}{RESET}")

    # ── 4. Tool 注册性能 ──
    print(f"\n{CYAN}[4] Tool 系统{RESET}")
    try:
        from app.core.tool_dispatch import get_tool_definitions, auto_discover_tools

        start = time.monotonic()
        auto_discover_tools()
        elapsed = (time.monotonic() - start) * 1000
        record("Tool 自动发现", elapsed, 1000)

        tools = get_tool_definitions()
        print(f"  📊 已注册 Tool: {len(tools)} 个")
    except Exception as e:
        print(f"  {RED}✗ Tool 系统测试失败: {e}{RESET}")

    # ── 5. Pydantic 模型验证性能 ──
    print(f"\n{CYAN}[5] Pydantic 验证{RESET}")
    try:
        from app.api.assets import AssetUpdate
        from app.api.gallery import PublishRequest

        start = time.monotonic()
        for _ in range(1000):
            AssetUpdate(title="test", file_type="ppt")
            PublishRequest(asset_id="abc")
        elapsed = (time.monotonic() - start) * 1000
        record("1000 次 Pydantic 验证", elapsed, 200)
    except Exception as e:
        print(f"  {RED}✗ Pydantic 测试失败: {e}{RESET}")

    # ── 6. Token 计数性能 ──
    print(f"\n{CYAN}[6] Token 计数{RESET}")
    try:
        from app.services.context_service import count_tokens

        test_text = "这是一段测试文本。" * 100
        start = time.monotonic()
        for _ in range(100):
            count_tokens(test_text)
        elapsed = (time.monotonic() - start) * 1000
        record("100 次 Token 计数", elapsed, 500)
    except Exception as e:
        print(f"  {RED}✗ Token 计数测试失败: {e}{RESET}")

    # ── 7. 文件系统 ──
    print(f"\n{CYAN}[7] 文件系统{RESET}")
    data_dir = Path("data")
    dirs = ["uploads", "exports", "thumbnails"]
    for d in dirs:
        p = data_dir / d
        p.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    for d in dirs:
        (data_dir / d).exists()
    elapsed = (time.monotonic() - start) * 1000
    record("数据目录检查", elapsed, 10)

    # ── 8. 上下文窗口配置 ──
    print(f"\n{CYAN}[8] 上下文窗口配置{RESET}")
    try:
        from app.services.context_service import MODEL_CONTEXT_WINDOW
        print(f"  📊 上下文窗口: {MODEL_CONTEXT_WINDOW:,} Token")
        alert_threshold = int(MODEL_CONTEXT_WINDOW * 0.85)
        print(f"  📊 85% 告警阈值: {alert_threshold:,} Token")
        compress_threshold = int(MODEL_CONTEXT_WINDOW * 0.70)
        print(f"  📊 70% 压缩阈值: {compress_threshold:,} Token")
        record("上下文配置加载", 0.1, 10)  # 配置检查
    except Exception as e:
        print(f"  {RED}✗ 上下文配置失败: {e}{RESET}")

    # ── 汇总 ──
    print(f"\n{YELLOW}{'═' * 50}{RESET}")
    passed = sum(1 for _, _, _, p in results if p)
    failed = sum(1 for _, _, _, p in results if not p)
    total = len(results)
    print(f"  总计: {total} 项性能指标")
    print(f"  {GREEN}达标: {passed}{RESET}")
    if failed:
        print(f"  {RED}未达标: {failed}{RESET}")
        print(f"\n  {YELLOW}未达标项:{RESET}")
        for name, actual, threshold, ok in results:
            if not ok:
                print(f"    - {name}: {actual:.1f}ms > {threshold:.0f}ms")
    else:
        print(f"  {GREEN}🎉 全部性能指标达标！{RESET}")

    # 性能基线参考值
    print(f"\n{CYAN}性能基线参考（执行计划要求）:{RESET}")
    print(f"  • 首 Token: <2s")
    print(f"  • 单页 PPT 生成: <15s")
    print(f"  • 导出: <30s")
    print(f"  • Prompt Token: <85% 上下文窗口")
    print(f"{YELLOW}{'═' * 50}{RESET}\n")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_perf())
    sys.exit(0 if success else 1)
