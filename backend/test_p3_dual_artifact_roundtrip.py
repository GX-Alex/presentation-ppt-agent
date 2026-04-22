import asyncio
import os
import tempfile
from pathlib import Path

import httpx


_TMPDIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR.name) / 'p3_test.db'}"
if not os.getenv("NATIVE_RENDERER_URL"):
    os.environ["NATIVE_RENDERER_URL"] = "http://127.0.0.1:4100"

from main import app
from app.models.database import async_session, init_db
from app.services import ppt_service


asyncio.run(init_db())


def test_dual_artifact_and_pptx_roundtrip_import() -> None:
    async def _run() -> None:
        async with async_session() as session:
            await ppt_service.create_presentation(
                session,
                task_id="task-p3-dual",
                presentation_id="pres-p3-dual",
                title="P3 Dual Artifact Workflow",
                theme_id="tech_dark",
                outline=[],
            )
            await ppt_service.save_slides(
                session,
                "pres-p3-dual",
                [
                    {
                        "index": 0,
                        "type": "two-column",
                        "html": (
                            "<section><h1>P3 双产物</h1><div style='display:flex; gap:24px'>"
                            "<div><h3>主产物</h3><p>Native PPTX 作为权威编辑产物。</p></div>"
                            "<div><h3>副产物</h3><p>HTML preview 从 DeckSpec 渲染，不再走 legacy 拼接。</p></div>"
                            "</div></section>"
                        ),
                        "speaker_notes": "p3-overview",
                    },
                    {
                        "index": 1,
                        "type": "chart",
                        "html": (
                            "<section><h1>关键指标</h1><p>导出成功率 99%</p>"
                            "<p>Preview 命中率 100%</p><p>Round-trip 回写 2</p></section>"
                        ),
                        "speaker_notes": "p3-metrics",
                    },
                ],
            )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            workflow_resp = await client.post(
                "/api/presentations/pres-p3-dual/workflows/native-pptx",
                json={"persist_artifact": True},
            )
            assert workflow_resp.status_code == 200
            workflow_data = workflow_resp.json()
            assert workflow_data["artifact"]["file_path"]
            assert workflow_data["artifact"]["preview_file_path"]
            assert workflow_data["artifact"]["preview_download_url"]
            assert workflow_data["artifact_variant_id"]
            assert workflow_data["html_artifact_variant_id"]
            assert workflow_data["preview"]["package_id"] == "official.html-preview-renderer"

            html_resp = await client.get("/api/presentations/pres-p3-dual/html")
            assert html_resp.status_code == 200
            assert 'data-deckspec-preview="true"' in html_resp.text
            assert "P3 双产物" in html_resp.text

            import_resp = await client.post(
                "/api/presentations/import/pptx",
                json={
                    "file_url": workflow_data["artifact"]["download_url"],
                    "title": "P3 Imported Roundtrip",
                },
            )
            assert import_resp.status_code == 200
            import_data = import_resp.json()
            assert import_data["success"] is True
            assert import_data["slide_count"] == 2
            imported_presentation_id = import_data["presentation_id"]
            assert imported_presentation_id != "pres-p3-dual"

            imported_pres_resp = await client.get(f"/api/presentations/{imported_presentation_id}")
            assert imported_pres_resp.status_code == 200
            imported_pres = imported_pres_resp.json()
            assert imported_pres["title"] == "P3 Imported Roundtrip"
            assert len(imported_pres["slides"]) == 2
            assert 'data-deckspec-preview="true"' in imported_pres["slides"][0]["html"]

            imported_html_resp = await client.get(f"/api/presentations/{imported_presentation_id}/html")
            assert imported_html_resp.status_code == 200
            assert 'data-deckspec-preview="true"' in imported_html_resp.text

            rerender_resp = await client.post(
                f"/api/presentations/{imported_presentation_id}/workflows/native-pptx",
                json={"persist_artifact": True},
            )
            assert rerender_resp.status_code == 200
            rerender_data = rerender_resp.json()
            assert rerender_data["artifact"]["file_path"]
            assert rerender_data["artifact"]["preview_file_path"]

    asyncio.run(_run())


def run_all_tests() -> None:
    test_dual_artifact_and_pptx_roundtrip_import()
    _TMPDIR.cleanup()
    print("P3 dual artifact and round-trip tests passed")


if __name__ == "__main__":
    run_all_tests()