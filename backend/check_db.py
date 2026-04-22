"""验证 Sprint 2 数据持久化和 HTML 组装"""
import asyncio
from app.models.database import init_db, async_session
from sqlalchemy import text

async def check():
    await init_db()
    async with async_session() as s:
        r = await s.execute(text("SELECT id, title FROM presentations ORDER BY created_at DESC LIMIT 1"))
        pres = r.first()
        print(f"最新 Presentation: {pres[0][:8]}... title={pres[1]}")

        r2 = await s.execute(text(
            f'SELECT "index", type, length(html) as html_len FROM slides '
            f'WHERE presentation_id="{pres[0]}" ORDER BY "index"'
        ))
        for row in r2.all():
            print(f"  幻灯片 {row[0]+1}: type={row[1]} html_len={row[2]}")

        from app.services.ppt_service import build_full_html
        html = await build_full_html(s, pres[0])
        if html:
            print(f"✅ 完整 HTML 已组装: {len(html)} 字符")
            with open("data/test_preview.html", "w") as f:
                f.write(html)
            print("✅ 已保存到 data/test_preview.html")
        else:
            print("❌ HTML 组装失败")

asyncio.run(check())
