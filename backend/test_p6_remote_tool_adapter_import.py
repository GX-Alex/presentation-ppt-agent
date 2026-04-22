import asyncio
import os
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select


_TMPDIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR.name) / 'p6_test.db'}"

from app.core.tool_dispatch import auto_discover_tools, dispatch, get_tool_definitions_for_user
from app.models.database import async_session, init_db
from app.models.tables import PluginVersion, Task
from app.services import remote_package_sources as remote_sources
from app.services.plugin_registry import import_plugin_source, install_registry_package
from app.services.ppt_service import create_presentation, save_slides
from app.services.user_settings_service import ensure_user


USER_ID = "default-user-00000000"
SOURCE_ID = "community.deckspec-inspector"
PACKAGE_ID = "community.deckspec-inspector"


asyncio.run(init_db())
auto_discover_tools()


async def _create_sample_presentation() -> str:
    presentation_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())

    async with async_session() as session:
        await ensure_user(session, user_id=USER_ID)
        session.add(Task(id=task_id, user_id=USER_ID, title="Remote Adapter Import Test"))
        await session.commit()
        await create_presentation(
            session,
            task_id=task_id,
            presentation_id=presentation_id,
            title="Remote Tool Adapter Deck",
            theme_id="tech_dark",
            outline=[{"title": "Overview", "bullets": ["One"], "type": "content"}],
        )
        await save_slides(
            session,
            presentation_id,
            [
                {
                    "index": 0,
                    "type": "content",
                    "html": "<section><h1>Overview</h1><p>Imported remote tool adapter</p></section>",
                    "speaker_notes": "remote-adapter",
                }
            ],
        )

    return presentation_id


def test_remote_tool_adapter_import_generates_llm_tools() -> None:
    async def _run() -> None:
        original_spec = remote_sources.REMOTE_PACKAGE_SOURCES.get(SOURCE_ID)
        original_list_dir = remote_sources._github_list_dir
        original_fetch_json_optional = remote_sources._github_fetch_json_file_optional
        original_fetch_text_optional = remote_sources._github_fetch_text_file_optional
        original_latest_commit = remote_sources._github_latest_commit

        remote_sources.REMOTE_PACKAGE_SOURCES[SOURCE_ID] = remote_sources.GitHubRemoteSource(
            source_id=SOURCE_ID,
            owner="example",
            repo="deckspec-tools",
            ref="main",
            package_id=PACKAGE_ID,
            plugin_path="packages/deckspec-inspector",
            package_kind="tool_adapter",
        )

        async def _fake_github_list_dir(client, owner, repo, path, ref):
            assert owner == "example"
            assert repo == "deckspec-tools"
            assert ref == "main"
            if path == "packages/deckspec-inspector":
                return [
                    {
                        "name": ".claude-plugin",
                        "path": f"{path}/.claude-plugin",
                        "type": "dir",
                        "download_url": None,
                        "html_url": f"https://github.com/{owner}/{repo}/tree/{ref}/{path}/.claude-plugin",
                    },
                    {
                        "name": "README.md",
                        "path": f"{path}/README.md",
                        "type": "file",
                        "download_url": f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}/README.md",
                        "html_url": f"https://github.com/{owner}/{repo}/blob/{ref}/{path}/README.md",
                    },
                ]
            raise AssertionError(f"Unexpected GitHub list dir path: {path}")

        async def _fake_fetch_json_optional(client, owner, repo, path, ref):
            if path.endswith(".claude-plugin/plugin.json"):
                return {
                    "name": "DeckSpec Inspector",
                    "version": "1.2.3",
                    "description": "Inspect canonical DeckSpec from GitHub imported adapter.",
                    "generalagent": {
                        "kind": "tool_adapter",
                        "entrypoints": [
                            {
                                "target": "deckspec.v1",
                                "description": "Inspect canonical DeckSpec for a presentation.",
                            }
                        ],
                    },
                }
            if path.endswith(".claude-plugin/marketplace.json"):
                return {
                    "name": "DeckSpec Inspector",
                    "metadata": {
                        "description": "Marketplace metadata for a deckspec inspection adapter.",
                    },
                }
            return {}

        async def _fake_fetch_text_optional(client, owner, repo, path, ref):
            if path.endswith("README.md"):
                return "# DeckSpec Inspector\n\nRead canonical DeckSpec from persisted presentations."
            return ""

        async def _fake_latest_commit(client, owner, repo, path, ref):
            return {
                "sha": "1234567890abcdef1234567890abcdef12345678",
                "commit": {
                    "author": {
                        "date": "2026-03-31T01:02:03Z",
                    }
                },
            }

        remote_sources._github_list_dir = _fake_github_list_dir
        remote_sources._github_fetch_json_file_optional = _fake_fetch_json_optional
        remote_sources._github_fetch_text_file_optional = _fake_fetch_text_optional
        remote_sources._github_latest_commit = _fake_latest_commit

        try:
            async with async_session() as session:
                await ensure_user(session, user_id=USER_ID)
                import_result = await import_plugin_source(session, USER_ID, SOURCE_ID)
                assert import_result["package_ids"] == [PACKAGE_ID]
                assert import_result["latest_manifest"]["kind"] == "tool_adapter"
                assert import_result["latest_manifest"]["version"] == "1.2.3"
                assert import_result["latest_manifest"]["entrypoints"][0]["target"] == "deckspec.v1"

                version_row = (
                    await session.execute(
                        select(PluginVersion)
                        .where(PluginVersion.package_id == PACKAGE_ID)
                        .where(PluginVersion.version == "1.2.3")
                    )
                ).scalar_one()
                resource_manifest = version_row.resource_manifest or {}
                llm_tools = resource_manifest.get("llm_tools") or []
                assert len(llm_tools) == 1
                generated_tool = llm_tools[0]
                assert generated_tool["adapter_target"] == "deckspec.v1"
                assert generated_tool["name"] == "deckspec_inspector_deckspec"
                assert generated_tool["parameters"]["required"] == ["presentation_id"]

                await install_registry_package(session, USER_ID, PACKAGE_ID)

            presentation_id = await _create_sample_presentation()

            async with async_session() as session:
                tool_names = {
                    definition["function"]["name"]
                    for definition in await get_tool_definitions_for_user(session, USER_ID)
                }
                assert "deckspec_inspector_deckspec" in tool_names

                tool_result = await dispatch(
                    "deckspec_inspector_deckspec",
                    {"presentation_id": presentation_id},
                    session=session,
                    user_id=USER_ID,
                )
                assert tool_result["presentation_id"] == presentation_id
                assert tool_result["package_id"] == PACKAGE_ID
                assert tool_result["slide_count"] == 1
                assert tool_result["deck_spec"]["deck_id"] == presentation_id
        finally:
            remote_sources._github_list_dir = original_list_dir
            remote_sources._github_fetch_json_file_optional = original_fetch_json_optional
            remote_sources._github_fetch_text_file_optional = original_fetch_text_optional
            remote_sources._github_latest_commit = original_latest_commit
            if original_spec is None:
                remote_sources.REMOTE_PACKAGE_SOURCES.pop(SOURCE_ID, None)
            else:
                remote_sources.REMOTE_PACKAGE_SOURCES[SOURCE_ID] = original_spec

    asyncio.run(_run())


def run_all_tests() -> None:
    test_remote_tool_adapter_import_generates_llm_tools()
    _TMPDIR.cleanup()
    print("P6 remote tool adapter import tests passed")


if __name__ == "__main__":
    run_all_tests()