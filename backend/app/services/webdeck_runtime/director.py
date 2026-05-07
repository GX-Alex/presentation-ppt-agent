"""
Deck Director — 总控角色 (对齐 high.md §5.3.1)。
负责接收 brief、确定全局目标、将 deck 任务拆给 Deck Planner。
这是 agent_loop → webdeck_runtime 的入口分流点。

重要: Director 自行管理数据库会话（通过 async_session），
调用方（chat_handler）只需传入 send_fn 和 model。
"""
import json
import logging
import uuid
from typing import Any, Callable, Awaitable

from app.core.llm_client import chat as llm_chat
from app.models.database import async_session
from sqlalchemy import select
from app.models.tables import TaskMessage, Task
from app.services.presentation_briefing_service import (
    prepare_planning_briefing,
)
from app.services.webdeck_runtime.contracts import (
    DeckManifest, DeckStatus, GlobalTheme, ReviewReport,
)
from app.services.webdeck_runtime.state_store import deck_state_store
from app.services.webdeck_runtime.planner import DeckPlanner
from app.services.webdeck_runtime.reviewer import DeckReviewer
from app.services.webdeck_runtime.scheduler import LaneScheduler

logger = logging.getLogger(__name__)


class DeckDirector:
    """
    Deck Director — Web Deck 编排运行时的入口控制器。
    对齐 high.md §4.2: 正确路线 A + B 的调度中枢。

    构造时接收 send_fn 和 model，所有方法内部自管 DB 会话。
    """

    def __init__(
        self,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
        model: str | None = None,
    ):
        self.send_fn = send_fn
        self.model = model
        self.planner = DeckPlanner()
        self.scheduler = LaneScheduler()
        self.reviewer = DeckReviewer()

    async def run(
        self,
        brief: dict,
        task_id: str,
        user_id: str | None = None,
    ) -> str:
        """
        执行完整的 deck 规划流程。

        Args:
            brief: 用户 brief (包含 topic, audience, style 等)
            task_id: 任务 ID
            user_id: 用户 ID（可选，默认使用 default）

        Returns:
            project_id: 创建的 deck 项目 ID
        """
        async with async_session() as session:
            prepared_brief = await self._prepare_brief(session, task_id, brief)

            # 1. 创建 Deck 项目
            title = prepared_brief.get("topic", "未命名演示")
            _user_id = user_id or "default"
            project = await deck_state_store.create_project(
                session=session,
                task_id=task_id,
                user_id=_user_id,
                title=title,
                brief=prepared_brief,
            )
            project_id = project.id

            await self._persist_brief_message(session, task_id, prepared_brief)

            await self.send_fn({
                "type": "webdeck_status",
                "project_id": project_id,
                "status": "planning",
                "message": "正在规划演示结构...",
            })

            try:
                # 2. 更新状态为 planning
                await deck_state_store.update_project_status(
                    session, project_id, DeckStatus.PLANNING.value
                )

                # 3. 调用 Planner 生成 DeckManifest
                manifest = await self.planner.plan(
                    session=session,
                    project_id=project_id,
                    brief=prepared_brief,
                    send_fn=self.send_fn,
                    model=self.model,
                )

                # 4. 保存 manifest 和创建页面记录
                await deck_state_store.save_manifest(session, project_id, manifest)
                await deck_state_store.create_pages_from_manifest(session, project_id, manifest)

                # 5. 创建版本快照
                await deck_state_store.create_version(
                    session, project_id, version=1,
                    manifest_snapshot=manifest.to_dict(),
                    change_summary="初始规划",
                )

                # 6. 推送 manifest 给前端
                await self.send_fn({
                    "type": "webdeck_manifest",
                    "project_id": project_id,
                    "manifest": manifest.to_dict(),
                })

                # 7. 更新状态为 plan_ready
                await deck_state_store.update_project_status(
                    session, project_id, DeckStatus.PLAN_READY.value
                )

                await self.send_fn({
                    "type": "webdeck_status",
                    "project_id": project_id,
                    "status": "plan_ready",
                    "message": f"规划完成！共 {len(manifest.pages)} 页，等待确认...",
                })

                return project_id

            except Exception as e:
                logger.exception(f"[Director] Deck 规划失败: {e}")
                await deck_state_store.update_project_status(
                    session, project_id, DeckStatus.FAILED.value
                )
                await self.send_fn({
                    "type": "webdeck_status",
                    "project_id": project_id,
                    "status": "failed",
                    "message": f"规划失败: {str(e)}",
                })
                raise

    async def _prepare_brief(
        self,
        session,
        task_id: str,
        brief: dict[str, Any],
    ) -> dict[str, Any]:
        prepared = dict(brief or {})
        prepared.update(
            await prepare_planning_briefing(
                session,
                task_id,
                prepared,
                send_status=self._send_preparation_status,
                model=self.model,
            )
        )
        return prepared

    async def _send_preparation_status(self, text: str) -> None:
        await self.send_fn({
            "type": "status",
            "text": text,
        })

    async def _persist_brief_message(
        self,
        session,
        task_id: str,
        brief: dict[str, Any],
    ) -> None:
        result = await session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if task is None:
            return

        if not task.title:
            task.title = str(brief.get("title") or brief.get("topic") or "Web Deck 任务")[:255]
        task.intent = "ppt"

        lines = [
            f"🎯 生成 Web Deck：{brief.get('topic') or '未命名主题'}",
            f"受众：{brief.get('audience') or '通用'}",
        ]
        if brief.get("goal"):
            lines.append(f"目标：{brief.get('goal')}")
        if brief.get("must_include"):
            values = brief.get("must_include")
            if isinstance(values, list):
                lines.append("必须覆盖：" + "；".join(str(item).strip() for item in values if str(item).strip()))
        if brief.get("attachments"):
            attachments = brief.get("attachments") or []
            lines.append("附件：" + "；".join(str(item.get("filename") or item.get("asset_id") or "附件") for item in attachments))
        if brief.get("reference_urls"):
            reference_urls = brief.get("reference_urls") or []
            lines.append("网址：" + "；".join(str(item).strip() for item in reference_urls if str(item).strip()))

        session.add(
            TaskMessage(
                id=str(uuid.uuid4()),
                task_id=task_id,
                role="user",
                content="\n".join(lines),
                msg_type="text",
            )
        )
        await session.commit()

    async def execute_generation(
        self,
        project_id: str,
    ) -> None:
        """
        执行页面生成 — 在用户确认 manifest 后调用。
        由 Scheduler 协调各页面的并行/串行执行。
        """
        async with async_session() as session:
            await deck_state_store.update_project_status(
                session, project_id, DeckStatus.GENERATING.value
            )

            await self.send_fn({
                "type": "webdeck_status",
                "project_id": project_id,
                "status": "generating",
                "message": "开始生成页面...",
            })

            pages = await deck_state_store.get_pages(session, project_id)
            await self.send_fn({
                "type": "webdeck_pages_init",
                "project_id": project_id,
                "pages": [
                    {
                        "id": page.page_id,
                        "pageIndex": page.page_index,
                        "title": page.title or f"第 {page.page_index + 1} 页",
                        "kind": page.page_kind or "content",
                        "status": "pending",
                        "lanes": [],
                    }
                    for page in pages
                ],
            })

            try:
                # 调用 Scheduler 执行所有页面的生成
                summary = await self.scheduler.run(
                    session=session,
                    project_id=project_id,
                    send_fn=self.send_fn,
                    model=self.model,
                )

                if summary["failed"] > 0:
                    raise ValueError(
                        f"页面生成未完成：{summary['completed']}/{summary['total']} 页成功，"
                        f"{summary['failed']} 页失败或被依赖阻断"
                    )

                await deck_state_store.update_project_status(
                    session, project_id, DeckStatus.REVIEWING.value
                )

                await self.send_fn({
                    "type": "webdeck_status",
                    "project_id": project_id,
                    "status": "reviewing",
                    "message": "页面生成完成，正在执行整 deck 审稿...",
                })

                deck_review = await self.reviewer.review_deck(
                    session=session,
                    project_id=project_id,
                    model=self.model,
                )
                await self._emit_review_event(project_id, "deck", project_id, deck_review)

                if not deck_review.passed:
                    raise ValueError(self._summarize_review_failure(deck_review))

                # 生成完成 — 组装最终 Deck
                await self._assemble_final_deck(session, project_id)

                await deck_state_store.update_project_status(
                    session, project_id, DeckStatus.COMPLETED.value
                )

                await self.send_fn({
                    "type": "webdeck_status",
                    "project_id": project_id,
                    "status": "completed",
                    "message": "Web Deck 生成完成！",
                })

            except Exception as e:
                logger.exception(f"[Director] 页面生成失败: {e}")
                await self._fail_open_pages(
                    session=session,
                    project_id=project_id,
                    reason="任务终止，未完成页面已停止。请查看工作台中的失败原因后重试。",
                )
                await deck_state_store.update_project_status(
                    session, project_id, DeckStatus.FAILED.value
                )
                await self.send_fn({
                    "type": "webdeck_status",
                    "project_id": project_id,
                    "status": "failed",
                    "message": f"生成失败: {str(e)}",
                })
                raise

    async def _fail_open_pages(
        self,
        session,
        project_id: str,
        reason: str,
    ) -> None:
        pages = await deck_state_store.get_pages(session, project_id)
        for page in pages:
            if page.status in {
                DeckStatus.COMPLETED.value,
                "completed",
                "failed",
            }:
                continue

            await deck_state_store.update_page_status(session, page.id, "failed")
            await self.send_fn({
                "type": "webdeck_page_ready",
                "project_id": project_id,
                "page_id": page.page_id,
                "page_index": page.page_index,
                "title": page.title,
                "html": "",
                "status": "failed",
                "error": reason,
            })

    async def _emit_review_event(
        self,
        project_id: str,
        level: str,
        target_id: str,
        report: ReviewReport,
    ) -> None:
        await self.send_fn({
            "type": "webdeck_review",
            "project_id": project_id,
            "level": level,
            "target_id": target_id,
            "passed": report.passed,
            "score": report.score,
            "issues": report.issues,
            "suggestions": report.suggestions,
            "retrying": False,
        })

    @staticmethod
    def _summarize_review_failure(report: ReviewReport) -> str:
        first_issue = report.issues[0] if report.issues else {}
        message = str(first_issue.get("message") or "Deck 级审稿未通过").strip()
        suggestion = str(first_issue.get("suggestion") or "").strip()
        if suggestion:
            return f"{message}；修正方向: {suggestion}"
        if report.suggestions:
            return f"{message}；修正方向: {report.suggestions[0]}"
        return message

    async def retry_page(
        self,
        project_id: str,
        page_id: str,
    ) -> None:
        """重试单个失败页面，不影响其他页面"""
        async with async_session() as session:
            await self.scheduler.retry_page(
                session=session,
                project_id=project_id,
                page_id=page_id,
                send_fn=self.send_fn,
                model=self.model,
            )

    async def retry_lane(
        self,
        project_id: str,
        page_id: str,
        lane_id: str,
    ) -> None:
        """重试单个失败 lane，不影响同页其他 lane"""
        async with async_session() as session:
            await self.scheduler.retry_lane(
                session=session,
                project_id=project_id,
                page_id=page_id,
                lane_id=lane_id,
                send_fn=self.send_fn,
                model=self.model,
            )

    async def _assemble_final_deck(
        self,
        session,
        project_id: str,
    ) -> None:
        """组装最终的 Web Deck — 将所有页面 HTML 合成一份完整 deck"""
        from app.services.webdeck_runtime.publish_service import republish_project

        pages = await deck_state_store.get_pages(session, project_id)
        publish, full_html = await republish_project(
            session=session,
            project_id=project_id,
            metadata={"source": "runtime_complete"},
        )

        # 推送最终 deck 给前端
        await self.send_fn({
            "type": "webdeck_complete",
            "project_id": project_id,
            "version": publish.version,
            "html": full_html,
            "page_count": len(pages),
        })
