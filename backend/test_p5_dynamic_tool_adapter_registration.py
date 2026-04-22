import asyncio
import os
import tempfile
import uuid
from pathlib import Path


_TMPDIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR.name) / 'p5_test.db'}"

from app.core.tool_dispatch import auto_discover_tools, dispatch, get_tool_definitions_for_user
from app.models.database import async_session, init_db
from app.models.tables import Task
from app.services.plugin_registry import _upsert_registry_manifest, install_registry_package, toggle_installed_package
from app.services.ppt_service import create_presentation, save_slides
from app.services.user_settings_service import ensure_user


USER_ID = "default-user-00000000"
PACKAGE_ID = "community.deckspec-inspector"
TOOL_NAME = "inspect_deckspec"


asyncio.run(init_db())
auto_discover_tools()


async def _seed_dynamic_tool_adapter() -> None:
    manifest = {
        "schema_version": "1.0.0",
        "package_id": PACKAGE_ID,
        "display_name": "DeckSpec Inspector",
        "kind": "tool_adapter",
        "version": "1.0.0",
        "description": "Expose a read-only DeckSpec inspection tool for installed presentations.",
        "publisher": "Community",
        "tags": ["deckspec", "inspection", "tool"],
        "capabilities": ["deckspec.inspect"],
        "permissions": [
            {"name": "registry.read", "rationale": "Read platform registry metadata for adapter resolution"},
        ],
        "compatibility": {
            "min_platform_version": "0.1.0",
            "target_artifact_mode": ["dual_render"],
        },
        "entrypoints": [
            {
                "kind": "adapter",
                "target": "deckspec.v1",
                "description": "Read canonical DeckSpec for a persisted presentation.",
            }
        ],
    }
    resource_manifest = {
        "llm_tools": [
            {
                "name": TOOL_NAME,
                "description": "Inspect the canonical DeckSpec of an existing presentation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "presentation_id": {
                            "type": "string",
                            "description": "The presentation ID to inspect.",
                        }
                    },
                    "required": ["presentation_id"],
                },
                "adapter_target": "deckspec.v1",
            }
        ]
    }

    async with async_session() as session:
        await ensure_user(session, user_id=USER_ID)
        await _upsert_registry_manifest(
            session,
            manifest,
            source="registry",
            source_ref="test-fixture",
            resource_manifest=resource_manifest,
        )
        await session.commit()
        await install_registry_package(session, USER_ID, PACKAGE_ID)


async def _create_sample_presentation() -> str:
    presentation_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())

    async with async_session() as session:
        await ensure_user(session, user_id=USER_ID)
        session.add(Task(id=task_id, user_id=USER_ID, title="Dynamic Tool Test"))
        await session.commit()
        await create_presentation(
            session,
            task_id=task_id,
            presentation_id=presentation_id,
            title="Dynamic Tool Deck",
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
                    "html": "<section><h1>Overview</h1><p>Dynamic tool adapter</p></section>",
                    "speaker_notes": "note",
                }
            ],
        )

    return presentation_id


def test_dynamic_tool_adapter_registration_and_dispatch() -> None:
    async def _run() -> None:
        await _seed_dynamic_tool_adapter()
        presentation_id = await _create_sample_presentation()

        async with async_session() as session:
            tool_names = {
                definition["function"]["name"]
                for definition in await get_tool_definitions_for_user(session, USER_ID)
            }
            assert TOOL_NAME in tool_names

            tool_result = await dispatch(
                TOOL_NAME,
                {"presentation_id": presentation_id},
                session=session,
                user_id=USER_ID,
            )
            assert tool_result["presentation_id"] == presentation_id
            assert tool_result["package_id"] == PACKAGE_ID
            assert tool_result["slide_count"] == 1
            assert tool_result["deck_spec"]["deck_id"] == presentation_id

            toggled = await toggle_installed_package(session, USER_ID, PACKAGE_ID, False)
            assert toggled is not None
            disabled_tool_names = {
                definition["function"]["name"]
                for definition in await get_tool_definitions_for_user(session, USER_ID)
            }
            assert TOOL_NAME not in disabled_tool_names

    asyncio.run(_run())


def run_all_tests() -> None:
    test_dynamic_tool_adapter_registration_and_dispatch()
    _TMPDIR.cleanup()
    print("P5 dynamic tool adapter tests passed")


if __name__ == "__main__":
    run_all_tests()