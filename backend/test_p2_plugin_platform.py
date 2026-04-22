import asyncio
import os
import tempfile
from pathlib import Path

import httpx


_TMPDIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR.name) / 'p2_test.db'}"
if not os.getenv("NATIVE_RENDERER_URL"):
    os.environ["NATIVE_RENDERER_URL"] = "http://127.0.0.1:4100"

from main import app
from app.models.database import async_session, init_db
from app.services import ppt_service
from app.services.package_runtime import MINIMAX_PPTX_PLUGIN


asyncio.run(init_db())


def test_minimax_plugin_import_lifecycle_and_runtime() -> None:
    async def _run() -> None:
        async with async_session() as session:
            await ppt_service.create_presentation(
                session,
                task_id="task-p2-plugin",
                presentation_id="pres-p2-plugin",
                title="MiniMax Plugin Workflow",
                theme_id="tech_dark",
                outline=[],
            )
            await ppt_service.save_slides(
                session,
                "pres-p2-plugin",
                [
                    {
                        "index": 0,
                        "type": "two-column",
                        "html": (
                            "<section><h1>插件工作流</h1><div style='display:flex; gap:24px'>"
                            "<div><h3>规划</h3><p>叙事链路、页面 archetype、信息密度。</p></div>"
                            "<div><p>安装成功率 98%</p><p>导出成功率 99%</p><p>返工页数 2</p></div></div></section>"
                        ),
                        "speaker_notes": "plugin-two-column",
                    },
                    {
                        "index": 1,
                        "type": "chart",
                        "html": (
                            "<section><h1>关键指标</h1><p>渲染成功率 99%</p>"
                            "<p>平均导出时长 12</p><p>回滚成功率 100%</p></section>"
                        ),
                        "speaker_notes": "plugin-chart",
                    },
                ],
            )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            import_resp = await client.post(
                "/api/packages/import",
                json={"source_id": "minimax.pptx-plugin"},
            )
            assert import_resp.status_code == 200
            import_data = import_resp.json()
            assert import_data["package_ids"] == [MINIMAX_PPTX_PLUGIN]
            assert import_data["versions"] == ["1.0.0"]
            assert import_data["source_ref"].startswith("github:MiniMax-AI/skills/plugins/pptx-plugin@")
            assert import_data["latest_manifest"]["version"] == "1.0.0"
            assert import_data["latest_manifest"]["publisher"] == "MiniMax-AI/skills"
            assert import_data["latest_manifest"]["metadata"]["source_repo"] == "MiniMax-AI/skills"

            registry_resp = await client.get("/api/packages/registry")
            assert registry_resp.status_code == 200
            registry_ids = {item["package_id"] for item in registry_resp.json()["items"]}
            assert MINIMAX_PPTX_PLUGIN in registry_ids

            versions_resp = await client.get(f"/api/packages/registry/{MINIMAX_PPTX_PLUGIN}/versions")
            assert versions_resp.status_code == 200
            versions_data = versions_resp.json()
            assert versions_data["latest_version"] == "1.0.0"
            assert [item["version"] for item in versions_data["versions"]] == ["1.0.0"]

            install_resp = await client.post(
                "/api/packages/install",
                json={"package_id": MINIMAX_PPTX_PLUGIN, "version": "1.0.0"},
            )
            assert install_resp.status_code == 200
            installed_ids = {item["package_id"] for item in install_resp.json()["installed_packages"]}
            assert installed_ids == {
                "official.deckspec-contract",
                "official.native-pptx-renderer",
                "minimax.pptx-generator-skillset",
                MINIMAX_PPTX_PLUGIN,
            }

            skills_resp = await client.get("/api/skills/", params={"include_disabled": True})
            assert skills_resp.status_code == 200
            imported_skills = [
                item
                for item in skills_resp.json()["skills"]
                if (item.get("validation_result") or {}).get("package_id") == MINIMAX_PPTX_PLUGIN
            ]
            assert {(item.get("validation_result") or {}).get("skill_id") for item in imported_skills} == {
                "color-font-skill",
                "design-style-skill",
                "ppt-editing-skill",
                "ppt-orchestra-skill",
                "slide-making-skill",
            }

            installed_resp = await client.get("/api/packages/installed")
            assert installed_resp.status_code == 200
            installed_items = installed_resp.json()["items"]
            minimax_package = next(item for item in installed_items if item["package_id"] == MINIMAX_PPTX_PLUGIN)
            assert minimax_package["version"] == "1.0.0"
            assert minimax_package["status"] == "installed"
            assert minimax_package["source"] == "imported"

            workflow_resp = await client.post(
                "/api/presentations/pres-p2-plugin/workflows/native-pptx",
                json={"package_id": MINIMAX_PPTX_PLUGIN, "persist_artifact": True},
            )
            assert workflow_resp.status_code == 200
            workflow_data = workflow_resp.json()
            assert workflow_data["workflow"]["package_id"] == MINIMAX_PPTX_PLUGIN
            assert workflow_data["renderer"]["package_id"] == "official.native-pptx-renderer"
            assert workflow_data["artifact"]["file_path"]
            assert workflow_data["artifact"]["preview_file_path"]
            assert workflow_data["artifact_variant_id"]
            assert workflow_data["html_artifact_variant_id"]

            bindings_resp = await client.get(
                "/api/packages/workflow-bindings",
                params={"presentation_id": "pres-p2-plugin", "package_id": MINIMAX_PPTX_PLUGIN},
            )
            assert bindings_resp.status_code == 200
            bindings = bindings_resp.json()["items"]
            assert len(bindings) == 1
            assert bindings[0]["package_id"] == MINIMAX_PPTX_PLUGIN

            workflow_logs_resp = await client.get(
                "/api/packages/execution-logs",
                params={"package_id": MINIMAX_PPTX_PLUGIN},
            )
            assert workflow_logs_resp.status_code == 200
            workflow_logs = workflow_logs_resp.json()["items"]
            assert any(item["execution_kind"] == "workflow" and item["status"] == "succeeded" for item in workflow_logs)
            assert any(item["execution_kind"] == "import" for item in workflow_logs)

            renderer_logs_resp = await client.get(
                "/api/packages/execution-logs",
                params={"package_id": "official.native-pptx-renderer"},
            )
            assert renderer_logs_resp.status_code == 200
            renderer_logs = renderer_logs_resp.json()["items"]
            assert any(item["execution_kind"] == "render" and item["status"] == "succeeded" for item in renderer_logs)

            variants_resp = await client.get(
                "/api/packages/artifact-variants",
                params={"presentation_id": "pres-p2-plugin", "package_id": MINIMAX_PPTX_PLUGIN},
            )
            assert variants_resp.status_code == 200
            variants = variants_resp.json()["items"]
            assert {item["variant_type"] for item in variants} == {"pptx-native", "html-preview"}
            assert all(item["file_url"] for item in variants)

    asyncio.run(_run())


def run_all_tests() -> None:
    test_minimax_plugin_import_lifecycle_and_runtime()
    _TMPDIR.cleanup()
    print("P2 plugin platform tests passed")


if __name__ == "__main__":
    run_all_tests()