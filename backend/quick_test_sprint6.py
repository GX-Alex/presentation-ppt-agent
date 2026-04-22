"""
Sprint 6 验证测试 — 资产管理 + 画廊 + 设置页。
运行方式: cd backend && python quick_test_sprint6.py
"""
import asyncio
import sys
import uuid
from datetime import datetime

# ──────────────── 颜色输出 ────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

passed = 0
failed = 0
results: list[tuple[str, bool, str]] = []


def ok(name: str, detail: str = ""):
    global passed
    passed += 1
    results.append((name, True, detail))
    print(f"  {GREEN}✓{RESET} {name}" + (f" — {detail}" if detail else ""))


def fail(name: str, detail: str = ""):
    global failed
    failed += 1
    results.append((name, False, detail))
    print(f"  {RED}✗{RESET} {name}" + (f" — {detail}" if detail else ""))


# ──────────────── 测试 ────────────────

async def run_tests():
    print(f"\n{YELLOW}═══ Sprint 6 验证测试 ═══{RESET}\n")

    # ── 1. 路由注册检查 ──
    print(f"{YELLOW}[1] 路由注册检查{RESET}")
    try:
        from main import app
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        for prefix in ["/api/assets", "/api/gallery"]:
            if any(prefix in r for r in routes):
                ok(f"路由 {prefix} 已注册")
            else:
                fail(f"路由 {prefix} 未注册", f"现有路由: {routes[:10]}")
    except Exception as e:
        fail("路由注册", str(e))

    # ── 2. Assets API 模型导入 ──
    print(f"\n{YELLOW}[2] Assets API 模块{RESET}")
    try:
        from app.api.assets import router as assets_router
        ok("assets router 导入成功")
        # 检查端点（路径包含 prefix）
        asset_paths = [r.path for r in assets_router.routes if hasattr(r, "path")]
        expected = ["/assets/", "/assets/stats", "/assets/{asset_id}"]
        for ep in expected:
            if ep in asset_paths:
                ok(f"Assets 端点 {ep}")
            else:
                fail(f"Assets 端点 {ep} 缺失", f"实际: {asset_paths}")
    except Exception as e:
        fail("assets 模块导入", str(e))

    # ── 3. Gallery API 模块 ──
    print(f"\n{YELLOW}[3] Gallery API 模块{RESET}")
    try:
        from app.api.gallery import router as gallery_router
        ok("gallery router 导入成功")
        gallery_paths = [r.path for r in gallery_router.routes if hasattr(r, "path")]
        expected = ["/gallery/", "/gallery/publish", "/gallery/{item_id}", "/gallery/{item_id}/fork"]
        for ep in expected:
            if ep in gallery_paths:
                ok(f"Gallery 端点 {ep}")
            else:
                fail(f"Gallery 端点 {ep} 缺失", f"实际: {gallery_paths}")
    except Exception as e:
        fail("gallery 模块导入", str(e))

    # ── 4. Asset Service ──
    print(f"\n{YELLOW}[4] Asset Service 模块{RESET}")
    try:
        from app.services.asset_service import (
            auto_settle_presentation,
            auto_settle_document,
            generate_image_thumbnail,
            update_asset_thumbnail,
        )
        ok("asset_service 函数导入成功")
    except Exception as e:
        fail("asset_service 导入", str(e))

    # ── 5. 数据库 CRUD 测试 ──
    print(f"\n{YELLOW}[5] 数据库 CRUD 测试{RESET}")
    try:
        from app.models.database import async_session, init_db
        from app.models.tables import Asset, GalleryItem

        await init_db()

        async with async_session() as session:
            # 创建测试 Asset
            test_id = f"test-{uuid.uuid4().hex[:8]}"
            asset = Asset(
                id=test_id,
                user_id="default-user-00000000",
                title="Sprint6 测试资产",
                file_type="ppt",
                source="generated",
                mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                file_url="/static/test.pptx",
                file_size=1024,
                metadata_={"test": True},
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(asset)
            await session.commit()
            ok(f"创建 Asset: {test_id}")

            # 读取
            from sqlalchemy import select
            result = await session.execute(select(Asset).where(Asset.id == test_id))
            fetched = result.scalar_one_or_none()
            if fetched and fetched.title == "Sprint6 测试资产":
                ok("读取 Asset 成功")
            else:
                fail("读取 Asset", "数据不匹配")

            # 更新
            fetched.title = "Sprint6 更新资产"
            await session.commit()
            await session.refresh(fetched)
            if fetched.title == "Sprint6 更新资产":
                ok("更新 Asset 成功")
            else:
                fail("更新 Asset")

            # Gallery: 发布
            gallery_id = f"gal-{uuid.uuid4().hex[:8]}"
            gi = GalleryItem(
                id=gallery_id,
                asset_id=test_id,
                author_id="default-user-00000000",
                category="ppt",
                title="测试画廊项目",
                version=1,
                license="cc-by-4.0",
                published_at=datetime.utcnow(),
            )
            session.add(gi)
            await session.commit()
            ok(f"创建 GalleryItem: {gallery_id}")

            # Gallery: 读取
            result2 = await session.execute(select(GalleryItem).where(GalleryItem.id == gallery_id))
            gal = result2.scalar_one_or_none()
            if gal and gal.title == "测试画廊项目":
                ok("读取 GalleryItem 成功")
            else:
                fail("读取 GalleryItem")

            # Gallery: Fork（模拟）
            fork_id = f"fork-{uuid.uuid4().hex[:8]}"
            forked = Asset(
                id=fork_id,
                user_id="default-user-00000000",
                title=f"{fetched.title} (Fork)",
                file_type=fetched.file_type,
                source="remix",
                parent_id=test_id,
                metadata_={"forked_from": gallery_id},
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(forked)
            gal.remix_count = (gal.remix_count or 0) + 1
            await session.commit()
            ok(f"Fork Asset: {fork_id}")

            # 验证 remix_count
            await session.refresh(gal)
            if gal.remix_count == 1:
                ok("remix_count 增加成功")
            else:
                fail("remix_count", f"expected 1, got {gal.remix_count}")

            # 清理测试数据
            await session.delete(gal)
            await session.delete(forked)
            await session.delete(fetched)
            await session.commit()
            ok("清理测试数据")

    except Exception as e:
        fail("数据库 CRUD", str(e))

    # ── 6. Pydantic 模型验证 ──
    print(f"\n{YELLOW}[6] Pydantic 模型验证{RESET}")
    try:
        from app.api.assets import AssetUpdate, AssetOut
        u = AssetUpdate(title="test", file_type="ppt")
        ok("AssetUpdate 验证通过")
        o = AssetOut(
            id="x", title="t", file_type="ppt", source="upload",
            created_at="2025-01-01T00:00:00", updated_at="2025-01-01T00:00:00"
        )
        ok("AssetOut 验证通过")
    except Exception as e:
        fail("Pydantic 模型", str(e))

    try:
        from app.api.gallery import PublishRequest, GalleryItemOut
        p = PublishRequest(asset_id="abc")
        ok("PublishRequest 验证通过")
        g = GalleryItemOut(
            id="x", asset_id="a", author_id="u", category="ppt"
        )
        ok("GalleryItemOut 验证通过")
    except Exception as e:
        fail("Gallery Pydantic 模型", str(e))

    # ── 7. file_service 集成点 ──
    print(f"\n{YELLOW}[7] file_service 集成{RESET}")
    try:
        from app.services.file_service import create_asset_record, ALLOWED_EXTENSIONS
        ok("create_asset_record 可用")
        if ".pptx" in ALLOWED_EXTENSIONS:
            ok("PPTX 在白名单中")
        else:
            fail("PPTX 不在白名单")
    except Exception as e:
        fail("file_service 集成", str(e))

    # ── 8. 辅助函数检查 ──
    print(f"\n{YELLOW}[8] 辅助函数检查{RESET}")
    try:
        from app.api.assets import _asset_to_dict
        ok("_asset_to_dict 可用")
    except Exception as e:
        fail("_asset_to_dict", str(e))

    try:
        from app.api.gallery import _gallery_to_dict
        ok("_gallery_to_dict 可用")
    except Exception as e:
        fail("_gallery_to_dict", str(e))

    # ── 汇总 ──
    print(f"\n{YELLOW}{'═' * 40}{RESET}")
    total = passed + failed
    print(f"  总计: {total} 项")
    print(f"  {GREEN}通过: {passed}{RESET}")
    if failed:
        print(f"  {RED}失败: {failed}{RESET}")
    print(f"{YELLOW}{'═' * 40}{RESET}\n")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
