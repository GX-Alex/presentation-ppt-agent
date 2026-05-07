"""
WebDeck 发布服务。
负责将当前页面 HTML 重新组装为整稿，并写入 deck_publishes。
"""
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import DeckProject, DeckPublish
from app.services.webdeck_runtime.artifact_composer import DeckComposer
from app.services.webdeck_runtime.contracts import DeckManifest
from app.services.webdeck_runtime.state_store import deck_state_store


async def republish_project(
    session: AsyncSession,
    project_id: str,
    metadata: dict | None = None,
) -> tuple[DeckPublish, str]:
    """基于最新页面内容重新发布项目，返回发布记录与整稿 HTML。"""
    project = await deck_state_store.get_project(session, project_id)
    if project is None:
        raise ValueError("项目不存在")
    if not project.manifest:
        raise ValueError("项目 manifest 不存在，无法重新发布")

    pages = await deck_state_store.get_pages(session, project_id)
    manifest = DeckManifest.from_dict(project.manifest)
    full_html = DeckComposer().compose(manifest, pages)

    max_publish_result = await session.execute(
        select(func.max(DeckPublish.version)).where(
            DeckPublish.project_id == project_id
        )
    )
    max_publish_version = int(max_publish_result.scalar() or 0)

    # 首次发布沿用项目当前版本；后续发布递增。
    publish_version = max_publish_version + 1 if max_publish_version > 0 else int(project.version or 1)

    if int(project.version or 0) != publish_version:
        await session.execute(
            update(DeckProject)
            .where(DeckProject.id == project_id)
            .values(version=publish_version, updated_at=datetime.utcnow())
        )
        await session.commit()

    publish = await deck_state_store.create_publish(
        session=session,
        project_id=project_id,
        version=publish_version,
        full_html=full_html,
        metadata=metadata,
    )
    return publish, full_html
