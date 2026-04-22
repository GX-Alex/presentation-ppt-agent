import asyncio
import os
import tempfile
from pathlib import Path

import httpx
from pydantic import ValidationError


_TMPDIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR.name) / 'p0_test.db'}"

from main import app
from app.core.agent_loop import SYSTEM_PROMPT
from app.core.tool_dispatch import auto_discover_tools, get_tool_definitions, get_tool_names, get_tool_runtime_metadata
from app.models.database import init_db
from app.schemas.deck_spec import DeckSpec
from app.schemas.package_manifest import PluginPackageManifest


asyncio.run(init_db())
auto_discover_tools()


def _expect_validation_error(factory) -> None:
    try:
        factory()
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError, but no exception was raised")


def test_legacy_ppt_generation_tools_are_hidden_from_llm():
    llm_visible = {
        definition["function"]["name"]
        for definition in get_tool_definitions()
    }
    all_tools = set(get_tool_names())

    assert "generate_outline" in all_tools
    assert "generate_slide" in all_tools
    assert "generate_ppt_deck" in all_tools
    assert "generate_outline" not in llm_visible
    assert "generate_slide" not in llm_visible
    assert "generate_ppt_deck" not in llm_visible

    runtime_metadata = get_tool_runtime_metadata("generate_ppt_deck")
    assert runtime_metadata is not None
    assert runtime_metadata["status"] == "legacy"
    assert runtime_metadata["replacement"] == "webdeck.quality_generation"


def test_agent_loop_prompt_stops_routing_zero_to_one_ppt_to_generate_ppt_deck():
    assert "优先调用 `generate_ppt_deck`" not in SYSTEM_PROMPT
    assert "不要再走旧的 `generate_ppt_deck` 工具链" in SYSTEM_PROMPT
    assert "Web Deck / 高质量生成入口" in SYSTEM_PROMPT


def test_deckspec_validates_unique_object_ids():
    valid_payload = {
        "deck_id": "deck-001",
        "artifact_mode": "dual_render",
        "title": "Native PPTX Test",
        "theme": {
            "theme_id": "executive_blue",
            "palette": {
                "background": "#0B1F33",
                "foreground": "#F8FAFC",
                "accent": "#4EA1FF",
                "muted": "#8AA0B8",
            },
            "typography": {
                "heading_font": "Aptos Display",
                "body_font": "Aptos",
                "mono_font": "Cascadia Code",
            },
            "spacing": {
                "base_unit": 8,
                "section_gap": 24,
                "item_gap": 12,
            },
        },
        "slide_size": {"width": 1920, "height": 1080, "unit": "px"},
        "slides": [
            {
                "slide_id": "slide-1",
                "title": "Cover",
                "page_type": "cover",
                "layout_id": "cover.hero",
                "nodes": [
                    {
                        "node_id": "node-1",
                        "kind": "text",
                        "role": "headline",
                        "bbox": {"x": 120, "y": 96, "w": 800, "h": 120},
                        "content": {"text": "Native PPTX-first"},
                    }
                ],
            }
        ],
    }

    deck = DeckSpec.model_validate(valid_payload)
    assert deck.artifact_mode == "dual_render"
    assert deck.slides[0].nodes[0].content["text"] == "Native PPTX-first"

    invalid_payload = dict(valid_payload)
    invalid_payload["slides"] = [
        {
            "slide_id": "slide-1",
            "title": "Duplicate IDs",
            "page_type": "content",
            "layout_id": "two-col",
            "nodes": [
                {
                    "node_id": "node-dup",
                    "kind": "text",
                    "role": "left",
                    "bbox": {"x": 0, "y": 0, "w": 100, "h": 100},
                    "content": {"text": "A"},
                },
                {
                    "node_id": "node-dup",
                    "kind": "text",
                    "role": "right",
                    "bbox": {"x": 120, "y": 0, "w": 100, "h": 100},
                    "content": {"text": "B"},
                },
            ],
        }
    ]

    _expect_validation_error(lambda: DeckSpec.model_validate(invalid_payload))


def test_plugin_manifest_permission_validation():
    manifest = PluginPackageManifest.model_validate(
        {
            "schema_version": "1.0.0",
            "package_id": "community.executive-theme-pack",
            "display_name": "Executive Theme Pack",
            "kind": "theme",
            "version": "1.2.0",
            "description": "A constrained enterprise presentation theme pack for Native PPTX decks.",
            "publisher": "Community",
            "permissions": [
                {"name": "registry.read", "rationale": "Read platform theme metadata"},
            ],
            "compatibility": {
                "min_platform_version": "0.1.0",
                "target_artifact_mode": ["native_pptx_first"],
            },
            "entrypoints": [
                {
                    "kind": "theme_bundle",
                    "target": "themes/executive",
                    "description": "Enterprise blue-gray design token bundle",
                }
            ],
        }
    )
    assert manifest.kind == "theme"
    assert manifest.permissions[0].name == "registry.read"

    _expect_validation_error(
        lambda: PluginPackageManifest.model_validate(
            {
                "schema_version": "1.0.0",
                "package_id": "bad.pkg",
                "display_name": "Bad",
                "kind": "workflow",
                "version": "1.0.0",
                "description": "Invalid permission manifest for testing.",
                "publisher": "Community",
                "permissions": [
                    {"name": "shell.exec", "rationale": "Should never be allowed"},
                ],
                "compatibility": {
                    "min_platform_version": "0.1.0",
                    "target_artifact_mode": ["native_pptx_first"],
                },
            }
        )
    )


def test_package_registry_api_and_dependency_install():
    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            registry_resp = await client.get("/api/packages/registry")
            assert registry_resp.status_code == 200
            registry_data = registry_resp.json()
            registry_ids = {item["package_id"] for item in registry_data["items"]}
            assert "official.deckspec-contract" in registry_ids
            assert "official.native-pptx-orchestrator" in registry_ids

            validate_resp = await client.post(
                "/api/packages/validate-manifest",
                json={
                    "manifest": {
                        "schema_version": "1.0.0",
                        "package_id": "community.strategy-skillset",
                        "display_name": "Strategy Skillset",
                        "kind": "skill",
                        "version": "0.2.0",
                        "description": "Provides structured strategy storytelling prompts.",
                        "publisher": "Community",
                        "permissions": [
                            {"name": "registry.read", "rationale": "Inspect dependency metadata"},
                        ],
                        "compatibility": {
                            "min_platform_version": "0.1.0",
                            "target_artifact_mode": ["dual_render"],
                        },
                    }
                },
            )
            assert validate_resp.status_code == 200
            assert validate_resp.json()["valid"] is True

            versions_resp = await client.get(
                "/api/packages/registry/official.native-pptx-orchestrator/versions"
            )
            assert versions_resp.status_code == 200
            versions_data = versions_resp.json()
            assert versions_data["latest_version"] == "0.2.0"
            assert versions_data["versions"][0]["version"] == "0.2.0"
            assert versions_data["versions"][1]["version"] == "0.1.0"

            install_resp = await client.post(
                "/api/packages/install",
                json={"package_id": "official.native-pptx-orchestrator", "version": "0.1.0"},
            )
            assert install_resp.status_code == 200
            install_data = install_resp.json()
            installed_ids = {pkg["package_id"] for pkg in install_data["installed_packages"]}
            assert installed_ids == {
                "official.deckspec-contract",
                "official.native-pptx-renderer",
                "official.html-preview-renderer",
                "minimax.pptx-generator-skillset",
                "official.native-pptx-orchestrator",
            }

            installed_resp = await client.get("/api/packages/installed")
            assert installed_resp.status_code == 200
            installed_items = installed_resp.json()["items"]
            assert len(installed_items) == 5
            orchestrator = next(
                item for item in installed_items if item["package_id"] == "official.native-pptx-orchestrator"
            )
            assert orchestrator["version"] == "0.1.0"
            assert orchestrator["upgrade_available"] is True
            assert orchestrator["latest_version"] == "0.2.0"

            compare_resp = await client.get(
                "/api/packages/official.native-pptx-orchestrator/compare",
                params={"from_version": "0.1.0", "to_version": "0.2.0"},
            )
            assert compare_resp.status_code == 200
            compare_data = compare_resp.json()
            assert compare_data["direction"] == "upgrade"
            assert "workflow.version_audit" in compare_data["added_capabilities"]

            upgrade_resp = await client.post(
                "/api/packages/official.native-pptx-orchestrator/upgrade",
                json={},
            )
            assert upgrade_resp.status_code == 200
            upgraded_ids = {pkg["package_id"] for pkg in upgrade_resp.json()["updated_packages"]}
            assert upgraded_ids == installed_ids

            upgraded_installed_resp = await client.get("/api/packages/installed")
            assert upgraded_installed_resp.status_code == 200
            upgraded_items = upgraded_installed_resp.json()["items"]
            upgraded_orchestrator = next(
                item for item in upgraded_items if item["package_id"] == "official.native-pptx-orchestrator"
            )
            assert upgraded_orchestrator["version"] == "0.2.0"
            assert upgraded_orchestrator["previous_version"] == "0.1.0"
            assert upgraded_orchestrator["status"] == "upgraded"

            rollback_resp = await client.post(
                "/api/packages/official.native-pptx-orchestrator/rollback"
            )
            assert rollback_resp.status_code == 200

            rolled_back_resp = await client.get("/api/packages/installed")
            assert rolled_back_resp.status_code == 200
            rolled_back_items = rolled_back_resp.json()["items"]
            rolled_back_orchestrator = next(
                item for item in rolled_back_items if item["package_id"] == "official.native-pptx-orchestrator"
            )
            assert rolled_back_orchestrator["version"] == "0.1.0"
            assert rolled_back_orchestrator["status"] == "rolled_back"

            toggle_resp = await client.post(
                "/api/packages/official.native-pptx-orchestrator/toggle",
                json={"enabled": False},
            )
            assert toggle_resp.status_code == 200
            assert toggle_resp.json()["item"]["is_enabled"] is False
            assert toggle_resp.json()["item"]["status"] == "disabled"

    asyncio.run(_run())


def run_all_tests() -> None:
    test_generate_ppt_deck_is_only_zero_to_one_ppt_tool()
    test_deckspec_validates_unique_object_ids()
    test_plugin_manifest_permission_validation()
    test_package_registry_api_and_dependency_install()
    _TMPDIR.cleanup()
    print("P0 tests passed")


if __name__ == "__main__":
    run_all_tests()