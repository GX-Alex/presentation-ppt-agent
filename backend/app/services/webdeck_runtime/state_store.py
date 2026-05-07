"""
状态存储 — 基于 Registry 模式的 Deck 状态管理 (参考 claw-code TaskRegistry)。
负责维护 deck/page/lane 的运行时状态，提供持久化读写接口。
线程安全的内存缓存 + 数据库持久化的双层架构。
"""
import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import (
    DeckProject, DeckPage, DeckVersion, LaneRun,
    DeckAssetNode, DeckReviewReport, DeckPublish, DeckPageVersion,
)
from app.services.webdeck_runtime.contracts import (
    DeckManifest, DeckStatus, PageStatus, LaneStatus,
)

logger = logging.getLogger(__name__)


class DeckStateStore:
    """
    Deck 状态注册表 — 单例模式，管理所有活跃 deck 的运行时状态。
    参考 claw-code 的 registry 模式：线程安全、可恢复、可审计。
    """

    def __init__(self):
        # 内存缓存: {project_id: {status, page_statuses, lane_statuses}}
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    # ────────────── Deck 项目 CRUD ──────────────

    async def create_project(
        self,
        session: AsyncSession,
        task_id: str,
        user_id: str,
        title: str,
        brief: dict | None = None,
    ) -> DeckProject:
        """创建新的 Deck 项目"""
        project = DeckProject(
            task_id=task_id,
            user_id=user_id,
            title=title,
            status=DeckStatus.DRAFT.value,
            brief=brief,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)

        # 初始化内存缓存
        async with self._lock:
            self._cache[project.id] = {
                "status": DeckStatus.DRAFT.value,
                "page_statuses": {},
                "lane_statuses": {},
            }

        logger.info(f"[StateStore] 创建 Deck 项目: {project.id} ({title})")
        return project

    async def get_project(self, session: AsyncSession, project_id: str) -> DeckProject | None:
        """获取 Deck 项目"""
        result = await session.execute(
            select(DeckProject)
            .execution_options(populate_existing=True)
            .where(DeckProject.id == project_id)
        )
        return result.scalar_one_or_none()

    async def get_project_by_task(self, session: AsyncSession, task_id: str) -> DeckProject | None:
        """根据 task_id 获取最新的 Deck 项目"""
        result = await session.execute(
            select(DeckProject)
            .execution_options(populate_existing=True)
            .where(DeckProject.task_id == task_id)
            .order_by(DeckProject.created_at.desc())
        )
        return result.scalars().first()

    async def update_project_status(
        self,
        session: AsyncSession,
        project_id: str,
        status: str,
    ) -> None:
        """更新项目状态"""
        await session.execute(
            update(DeckProject)
            .where(DeckProject.id == project_id)
            .values(status=status, updated_at=datetime.utcnow())
        )
        await session.commit()

        async with self._lock:
            if project_id in self._cache:
                self._cache[project_id]["status"] = status

        logger.info(f"[StateStore] 项目状态更新: {project_id} -> {status}")

    async def save_manifest(
        self,
        session: AsyncSession,
        project_id: str,
        manifest: DeckManifest,
    ) -> None:
        """保存 DeckManifest 到项目"""
        manifest_dict = manifest.to_dict()
        await session.execute(
            update(DeckProject)
            .where(DeckProject.id == project_id)
            .values(
                manifest=manifest_dict,
                title=manifest.title,
                subtitle=manifest.subtitle,
                global_theme=manifest.global_theme.to_dict(),
                updated_at=datetime.utcnow(),
            )
        )
        await session.commit()
        logger.info(f"[StateStore] 保存 Manifest: {project_id} ({manifest.title})")

    # ────────────── 页面 CRUD ──────────────

    async def create_pages_from_manifest(
        self,
        session: AsyncSession,
        project_id: str,
        manifest: DeckManifest,
    ) -> list[DeckPage]:
        """从 manifest 创建所有页面记录"""
        pages = []
        for idx, page_spec in enumerate(manifest.pages):
            page = DeckPage(
                project_id=project_id,
                page_id=page_spec.page_id,
                page_index=idx,
                title=page_spec.title,
                page_kind=page_spec.page_kind,
                status=PageStatus.PENDING.value,
                page_spec=page_spec.to_dict(),
            )
            session.add(page)
            pages.append(page)

        await session.commit()
        for p in pages:
            await session.refresh(p)

        # 更新内存缓存
        async with self._lock:
            if project_id in self._cache:
                self._cache[project_id]["page_statuses"] = {
                    p.page_id: PageStatus.PENDING.value for p in pages
                }

        logger.info(f"[StateStore] 创建 {len(pages)} 个页面: project={project_id}")
        return pages

    async def get_pages(self, session: AsyncSession, project_id: str) -> list[DeckPage]:
        """获取项目的所有页面（按顺序）"""
        result = await session.execute(
            select(DeckPage)
            .execution_options(populate_existing=True)
            .where(DeckPage.project_id == project_id)
            .order_by(DeckPage.page_index)
        )
        return list(result.scalars().all())

    async def get_page(self, session: AsyncSession, page_db_id: str) -> DeckPage | None:
        """根据数据库 ID 获取页面"""
        result = await session.execute(
            select(DeckPage)
            .execution_options(populate_existing=True)
            .where(DeckPage.id == page_db_id)
        )
        return result.scalar_one_or_none()

    async def get_page_by_page_id(
        self,
        session: AsyncSession,
        project_id: str,
        page_id: str,
    ) -> DeckPage | None:
        """根据 project_id + page_id 获取页面"""
        result = await session.execute(
            select(DeckPage)
            .execution_options(populate_existing=True)
            .where(DeckPage.project_id == project_id)
            .where(DeckPage.page_id == page_id)
        )
        return result.scalar_one_or_none()

    async def update_page_status(
        self,
        session: AsyncSession,
        page_db_id: str,
        status: str,
    ) -> None:
        """更新页面状态"""
        await session.execute(
            update(DeckPage)
            .where(DeckPage.id == page_db_id)
            .values(status=status, updated_at=datetime.utcnow())
        )
        await session.commit()

    async def save_page_html(
        self,
        session: AsyncSession,
        page_db_id: str,
        html: str,
        bundle: dict | None = None,
        status: str | None = None,
    ) -> None:
        """保存页面的渲染 HTML 和 bundle"""
        values: dict[str, Any] = {
            "html": html,
            "status": status or PageStatus.COMPLETED.value,
            "updated_at": datetime.utcnow(),
        }
        if bundle:
            values["page_bundle"] = bundle
        await session.execute(
            update(DeckPage).where(DeckPage.id == page_db_id).values(**values)
        )
        await session.commit()

    # ────────────── Lane 运行记录 ──────────────

    async def create_lane(
        self,
        session: AsyncSession,
        page_db_id: str,
        project_id: str,
        lane_id: str,
        kind: str,
        input_data: dict | None = None,
    ) -> LaneRun:
        """创建 lane 运行记录"""
        lane = LaneRun(
            page_id=page_db_id,
            project_id=project_id,
            lane_id=lane_id,
            kind=kind,
            status=LaneStatus.PENDING.value,
            input_data=input_data or {},
        )
        session.add(lane)
        await session.commit()
        await session.refresh(lane)
        return lane

    async def update_lane_status(
        self,
        session: AsyncSession,
        lane_db_id: str,
        status: str,
        output_data: dict | None = None,
        error: str | None = None,
        retries: int | None = None,
    ) -> None:
        """更新 lane 状态"""
        values: dict[str, Any] = {"status": status}
        if status == LaneStatus.RUNNING.value:
            values["started_at"] = datetime.utcnow()
        if status in (LaneStatus.COMPLETED.value, LaneStatus.FAILED.value):
            values["completed_at"] = datetime.utcnow()
        if output_data is not None:
            values["output_data"] = output_data
        if error is not None:
            values["error"] = error
        if retries is not None:
            values["retries"] = retries
        await session.execute(
            update(LaneRun).where(LaneRun.id == lane_db_id).values(**values)
        )
        await session.commit()

    async def get_page_lanes(self, session: AsyncSession, page_db_id: str) -> list[LaneRun]:
        """获取页面的所有 lane"""
        result = await session.execute(
            select(LaneRun).where(LaneRun.page_id == page_db_id)
        )
        return list(result.scalars().all())

    # ────────────── 资产节点 ──────────────

    async def save_asset(
        self,
        session: AsyncSession,
        page_db_id: str,
        project_id: str,
        asset_id: str,
        kind: str,
        content: str,
        metadata: dict | None = None,
    ) -> DeckAssetNode:
        """保存资产节点"""
        node = DeckAssetNode(
            page_id=page_db_id,
            project_id=project_id,
            asset_id=asset_id,
            kind=kind,
            content=content,
            metadata_=metadata or {},
        )
        session.add(node)
        await session.commit()
        await session.refresh(node)
        return node

    # ────────────── 审稿报告 ──────────────

    async def save_review(
        self,
        session: AsyncSession,
        project_id: str,
        page_db_id: str | None,
        level: str,
        passed: bool,
        score: float,
        issues: list | None = None,
        suggestions: list | None = None,
    ) -> DeckReviewReport:
        """保存审稿报告"""
        report = DeckReviewReport(
            project_id=project_id,
            page_id=page_db_id,
            level=level,
            passed=passed,
            score=score,
            issues=issues or [],
            suggestions=suggestions or [],
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return report

    async def get_reviews(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> list[DeckReviewReport]:
        """获取项目所有审稿报告"""
        stmt = select(DeckReviewReport).where(
            DeckReviewReport.project_id == project_id
        ).order_by(DeckReviewReport.created_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ────────────── 版本管理 ──────────────

    async def create_version(
        self,
        session: AsyncSession,
        project_id: str,
        version: int,
        manifest_snapshot: dict,
        change_summary: str | None = None,
    ) -> DeckVersion:
        """创建版本快照"""
        ver = DeckVersion(
            project_id=project_id,
            version=version,
            manifest_snapshot=manifest_snapshot,
            change_summary=change_summary,
        )
        session.add(ver)
        await session.commit()
        await session.refresh(ver)
        return ver

    async def create_page_version(
        self,
        session: AsyncSession,
        project_id: str,
        page_db_id: str,
        html: str,
        source: str = "manual",
        change_summary: str | None = None,
        metadata: dict | None = None,
    ) -> DeckPageVersion:
        """创建单页 HTML 版本快照。"""
        max_version_result = await session.execute(
            select(func.max(DeckPageVersion.version)).where(
                DeckPageVersion.page_db_id == page_db_id
            )
        )
        next_version = int(max_version_result.scalar() or 0) + 1

        page_version = DeckPageVersion(
            project_id=project_id,
            page_db_id=page_db_id,
            version=next_version,
            source=source,
            html=html,
            change_summary=change_summary,
            metadata_=metadata or {},
        )
        session.add(page_version)
        await session.commit()
        await session.refresh(page_version)
        return page_version

    async def list_page_versions(
        self,
        session: AsyncSession,
        page_db_id: str,
        limit: int = 20,
    ) -> list[DeckPageVersion]:
        """按版本号倒序获取页面版本历史。"""
        stmt = (
            select(DeckPageVersion)
            .where(DeckPageVersion.page_db_id == page_db_id)
            .order_by(DeckPageVersion.version.desc(), DeckPageVersion.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_page_version_by_number(
        self,
        session: AsyncSession,
        page_db_id: str,
        version: int,
    ) -> DeckPageVersion | None:
        """根据页面数据库 ID + 版本号获取版本快照。"""
        result = await session.execute(
            select(DeckPageVersion)
            .where(DeckPageVersion.page_db_id == page_db_id)
            .where(DeckPageVersion.version == version)
        )
        return result.scalar_one_or_none()

    # ────────────── 发布 ──────────────

    async def create_publish(
        self,
        session: AsyncSession,
        project_id: str,
        version: int,
        full_html: str,
        metadata: dict | None = None,
    ) -> DeckPublish:
        """创建发布记录"""
        pub = DeckPublish(
            project_id=project_id,
            version=version,
            full_html=full_html,
            metadata_=metadata or {},
        )
        session.add(pub)
        await session.commit()
        await session.refresh(pub)
        return pub

    # ────────────── 汇总查询 ──────────────

    async def get_project_summary(self, session: AsyncSession, project_id: str) -> dict:
        """获取项目运行时汇总状态 — 供前端状态面板消费"""
        project = await self.get_project(session, project_id)
        if not project:
            return {}

        pages = await self.get_pages(session, project_id)
        page_summaries = []
        for page in pages:
            lanes = await self.get_page_lanes(session, page.id)
            page_summaries.append({
                "page_id": page.page_id,
                "page_index": page.page_index,
                "title": page.title,
                "page_kind": page.page_kind,
                "status": page.status,
                "has_html": bool(page.html),
                "lanes": [
                    {
                        "lane_id": l.lane_id,
                        "kind": l.kind,
                        "status": l.status,
                        "error": l.error,
                    }
                    for l in lanes
                ],
            })

        return {
            "project_id": project.id,
            "title": project.title,
            "status": project.status,
            "version": project.version,
            "total_pages": len(pages),
            "completed_pages": sum(1 for p in pages if p.status == PageStatus.COMPLETED.value),
            "failed_pages": sum(1 for p in pages if p.status == PageStatus.FAILED.value),
            "pages": page_summaries,
        }


# 模块级单例
deck_state_store = DeckStateStore()
