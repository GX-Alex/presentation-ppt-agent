"""
Lane Scheduler — 页面调度器 (对齐 high.md §5.2 Lane Scheduler)。
负责按依赖关系执行所有页面的生成，支持失败重试和局部重跑。
"""
import asyncio
import logging
from collections import defaultdict, deque
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import async_session
from app.services.webdeck_runtime.contracts import DeckManifest, LaneStatus, PageStatus
from app.services.webdeck_runtime.page_orchestrator import PageOrchestrator
from app.services.webdeck_runtime.state_store import deck_state_store

logger = logging.getLogger(__name__)

DEFAULT_MAX_PAGE_CONCURRENCY = 8

# 页面级超时（秒）— 单页生成最多允许的执行时间
# 高价值页面有 3 条 lane，每条 lane 的 LLM 最长约 120s；多轮审稿重试再加一倍
# 300s 不够，改为 600s (10分钟)
DEFAULT_PAGE_TIMEOUT_S = 600  # 10 分钟

# 高价值页面类型需要更长超时（多 lane + 多轮审稿 + diagram 可能很慢）
PAGE_TIMEOUT_OVERRIDES: dict[str, int] = {
    "architecture": 900,
    "summary": 900,
}

# 软依赖：依赖页失败时仍允许尝试生成（缺少上下文但不级联失败）
SOFT_DEPENDENCY_KINDS: set[str] = {"content", "comparison", "closing", "appendix"}

# asyncio.wait 轮询超时（秒）— 防止所有任务挂起时调度器永远阻塞
WAIT_POLL_TIMEOUT_S = 60  # 每 60 秒检查一次


class LaneScheduler:
    """协调所有页面的依赖感知并发执行。"""

    def __init__(self, max_page_concurrency: int = DEFAULT_MAX_PAGE_CONCURRENCY):
        self.page_orchestrator = PageOrchestrator()
        self.max_page_concurrency = max(1, max_page_concurrency)

    async def run(
        self,
        session: AsyncSession,
        project_id: str,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
        model: str | None = None,
    ) -> dict[str, int]:
        """按依赖关系执行所有页面。独立页并发，受依赖页等待上游完成。"""
        project = await deck_state_store.get_project(session, project_id)
        if not project or not project.manifest:
            raise ValueError(f"项目不存在或没有 manifest: {project_id}")

        manifest = DeckManifest.from_dict(project.manifest)
        global_theme = project.global_theme or manifest.global_theme.to_dict()
        pages = await deck_state_store.get_pages(session, project_id)
        if not pages:
            return {"total": 0, "completed": 0, "failed": 0}

        pages_by_id = {page.page_id: page for page in pages}
        dependencies: dict[str, set[str]] = {}
        dependents: dict[str, set[str]] = defaultdict(set)
        ready: deque[str] = deque()
        blocked: set[str] = set()
        running: dict[asyncio.Task[tuple[str, bool, str | None]], str] = {}

        started = 0
        completed = 0
        failed = 0
        total = len(pages)

        for page in pages:
            page_spec = page.page_spec or {}
            current_dependencies = {
                dep for dep in page_spec.get("dependencies", [])
                if dep and dep != page.page_id
            }
            dependencies[page.page_id] = current_dependencies
            for dep in current_dependencies:
                dependents[dep].add(page.page_id)

        invalid_pages = [
            page_id
            for page_id, deps in dependencies.items()
            if any(dep not in pages_by_id for dep in deps)
        ]
        for page_id in invalid_pages:
            missing = sorted(dep for dep in dependencies[page_id] if dep not in pages_by_id)
            newly_failed = await self._mark_page_failed_by_dependency(
                project_id=project_id,
                page_id=page_id,
                page_index=pages_by_id[page_id].page_index,
                title=pages_by_id[page_id].title or page_id,
                missing_dependencies=missing,
                send_fn=send_fn,
            )
            blocked.update(newly_failed)
            failed += len(newly_failed)

        for page_id, deps in dependencies.items():
            if page_id in blocked:
                continue
            page = pages_by_id[page_id]
            # 跳过已完成的页面 — 恢复执行时避免重复生成
            if page.status == PageStatus.COMPLETED.value and page.html:
                completed += 1
                # 立即解锁依赖此页的下游页面
                for dependent_id in dependents.get(page_id, set()):
                    dependencies[dependent_id].discard(page_id)
                continue
            if not deps:
                ready.append(page_id)

        while ready or running:
            while ready and len(running) < self.max_page_concurrency:
                page_id = ready.popleft()
                if page_id in blocked:
                    continue

                page = pages_by_id[page_id]
                page_kind = getattr(page, "page_kind", None) or "content"
                page_timeout = PAGE_TIMEOUT_OVERRIDES.get(page_kind, DEFAULT_PAGE_TIMEOUT_S)
                started += 1
                await send_fn({
                    "type": "webdeck_progress",
                    "project_id": project_id,
                    "current": started,
                    "total": total,
                    "page_id": page.page_id,
                    "page_title": page.title,
                    "completed": completed,
                    "failed": failed,
                })

                task = asyncio.create_task(
                    asyncio.wait_for(
                        self._run_page_with_fresh_session(
                            page_db_id=page.id,
                            project_id=project_id,
                            global_theme=global_theme,
                            send_fn=send_fn,
                            model=model,
                        ),
                        timeout=page_timeout,
                    )
                )
                running[task] = (page_id, page_timeout)

            if not running:
                break

            done, _ = await asyncio.wait(
                running.keys(),
                return_when=asyncio.FIRST_COMPLETED,
                timeout=WAIT_POLL_TIMEOUT_S,
            )

            if not done:
                # 超时但无任务完成 — 检查是否所有任务仍在运行
                logger.debug(
                    "[Scheduler] wait 超时，无任务完成: project=%s running=%d ready=%d",
                    project_id, len(running), len(ready),
                )
                continue

            for task in done:
                page_id, actual_timeout = running.pop(task)
                try:
                    _, success, error = await task
                except asyncio.TimeoutError:
                    success = False
                    error = f"页面生成超时 ({actual_timeout}s)"
                    logger.warning(
                        "[Scheduler] 页面超时: project=%s page=%s timeout=%ss",
                        project_id, page_id, actual_timeout,
                    )
                    # 将超时页面标记为失败并通知前端
                    page = pages_by_id.get(page_id)
                    if page:
                        try:
                            async with async_session() as timeout_session:
                                await deck_state_store.update_page_status(
                                    timeout_session, page.id, PageStatus.FAILED.value
                                )
                            await send_fn({
                                "type": "webdeck_page_ready",
                                "project_id": project_id,
                                "page_id": page.page_id,
                                "page_index": page.page_index,
                                "title": page.title,
                                "html": "",
                                "status": "failed",
                                "error": error,
                            })
                        except Exception:
                            logger.debug("[Scheduler] 超时页面状态更新失败: %s", page_id)
                if success:
                    completed += 1
                    for dependent_id in dependents.get(page_id, set()):
                        if dependent_id in blocked:
                            continue
                        dependencies[dependent_id].discard(page_id)
                        if not dependencies[dependent_id] and dependent_id not in ready and dependent_id not in {pid for pid, _ in running.values()}:
                            ready.append(dependent_id)
                    continue

                failed += 1
                logger.warning(
                    "[Scheduler] 页面生成失败: project=%s page=%s error=%s",
                    project_id,
                    page_id,
                    error,
                )
                newly_failed = await self._cascade_dependency_failure(
                    project_id=project_id,
                    failed_page_id=page_id,
                    pages_by_id=pages_by_id,
                    dependencies=dependencies,
                    dependents=dependents,
                    blocked=blocked,
                    send_fn=send_fn,
                )
                failed += len(newly_failed)

        unresolved_pages = [
            page_id for page_id in pages_by_id
            if page_id not in blocked and page_id in dependencies and dependencies[page_id]
        ]
        if unresolved_pages:
            unresolved_failed = await self._mark_unresolved_pages(
                project_id=project_id,
                unresolved_page_ids=unresolved_pages,
                pages_by_id=pages_by_id,
                send_fn=send_fn,
            )
            failed += len(unresolved_failed)
            blocked.update(unresolved_failed)

        logger.info(
            "[Scheduler] 执行完成: project=%s total=%s completed=%s failed=%s",
            project_id,
            total,
            completed,
            failed,
        )

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
        }

    async def retry_page(
        self,
        session: AsyncSession,
        project_id: str,
        page_id: str,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
        model: str | None = None,
    ) -> None:
        """重试指定页面 — 只重跑该页，不影响其他页面。"""
        project = await deck_state_store.get_project(session, project_id)
        if not project or not project.manifest:
            raise ValueError(f"项目不存在: {project_id}")

        manifest = DeckManifest.from_dict(project.manifest)
        global_theme = project.global_theme or manifest.global_theme.to_dict()

        pages = await deck_state_store.get_pages(session, project_id)
        target_page = next((page for page in pages if page.page_id == page_id), None)
        if not target_page:
            raise ValueError(f"页面不存在: {page_id}")

        logger.info("[Scheduler] 重试页面: project=%s page=%s", project_id, page_id)
        await deck_state_store.update_page_status(session, target_page.id, PageStatus.RETRYING.value)

        await send_fn({
            "type": "webdeck_status",
            "project_id": project_id,
            "status": "retrying",
            "message": f"正在重试页面: {target_page.title}",
        })

        # K2: warn if dependencies not completed, but still allow retry
        try:
            async with async_session() as _dep_session:
                _pages = await deck_state_store.get_pages(_dep_session, project_id)
                _page = next((p for p in _pages if p.page_id == page_id), None)
                if _page:
                    _spec = _page.page_spec or {}
                    _deps = _spec.get("dependencies", []) if isinstance(_spec, dict) else []
                    if _deps:
                        _pages_map = {p.page_id: p for p in _pages}
                        _failed_deps = []
                        for _dep_id in _deps:
                            _dep_page = _pages_map.get(_dep_id)
                            if _dep_page and _dep_page.status != "completed":
                                _failed_deps.append(_dep_id)
                        if _failed_deps:
                            logger.warning(
                                f"[Scheduler] retrying page {page_id} with "
                                f"incomplete deps {_failed_deps} — proceeding anyway"
                            )
        except Exception as _k2_err:
            logger.debug(f"[K2] dep check skipped: {_k2_err}")
        # existing retry logic continues unchanged below

        try:
            async with async_session() as retry_session:
                page = await deck_state_store.get_page(retry_session, target_page.id)
                if not page:
                    raise ValueError(f"页面不存在: {page_id}")
                await self.page_orchestrator.generate_page(
                    session=retry_session,
                    page=page,
                    project_id=project_id,
                    global_theme=global_theme,
                    send_fn=send_fn,
                    model=model,
                )
        except Exception as e:
            logger.exception("[Scheduler] 页面重试失败: page=%s: %s", page_id, e)
            raise

    async def retry_lane(
        self,
        session: AsyncSession,
        project_id: str,
        page_id: str,
        lane_id: str,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
        model: str | None = None,
    ) -> None:
        """重试指定 lane — 只重跑该 lane，不影响同页其他 lane。"""
        from app.services.webdeck_runtime.lane_runner import LaneRunner

        pages = await deck_state_store.get_pages(session, project_id)
        target_page = next((page for page in pages if page.page_id == page_id), None)
        if not target_page:
            raise ValueError(f"页面不存在: {page_id}")

        lanes = await deck_state_store.get_page_lanes(session, target_page.id)
        target_lane = next((lane for lane in lanes if lane.lane_id == lane_id), None)
        if not target_lane:
            raise ValueError(f"Lane 不存在: {lane_id}")

        logger.info(
            "[Scheduler] 重试 lane: project=%s page=%s lane=%s",
            project_id,
            page_id,
            lane_id,
        )
        await deck_state_store.update_lane_status(session, target_lane.id, LaneStatus.RETRYING.value)

        runner = LaneRunner()
        try:
            await runner.run_lane(session=session, lane=target_lane, model=model)
            await send_fn({
                "type": "webdeck_lane_status",
                "project_id": project_id,
                "page_id": page_id,
                "lane_id": lane_id,
                "kind": target_lane.kind,
                "status": "completed",
            })
        except Exception as e:
            logger.exception("[Scheduler] Lane 重试失败: lane=%s: %s", lane_id, e)
            raise

    async def _run_page_with_fresh_session(
        self,
        page_db_id: str,
        project_id: str,
        global_theme: dict,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
        model: str | None,
    ) -> tuple[str, bool, str | None]:
        async with async_session() as task_session:
            page = await deck_state_store.get_page(task_session, page_db_id)
            if not page:
                return page_db_id, False, "页面记录不存在"
            try:
                await self.page_orchestrator.generate_page(
                    session=task_session,
                    page=page,
                    project_id=project_id,
                    global_theme=global_theme,
                    send_fn=send_fn,
                    model=model,
                )
                return page.page_id, True, None
            except Exception as exc:
                return page.page_id, False, str(exc)

    async def _cascade_dependency_failure(
        self,
        project_id: str,
        failed_page_id: str,
        pages_by_id: dict[str, Any],
        dependencies: dict[str, set[str]],
        dependents: dict[str, set[str]],
        blocked: set[str],
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> list[str]:
        queue = deque(dependents.get(failed_page_id, set()))
        newly_failed: list[str] = []

        while queue:
            page_id = queue.popleft()
            if page_id in blocked:
                continue

            page = pages_by_id[page_id]
            page_kind = getattr(page, "page_kind", None) or "content"

            # 软依赖页面：移除对失败页的依赖，允许其继续排队生成
            if page_kind in SOFT_DEPENDENCY_KINDS:
                dependencies[page_id].discard(failed_page_id)
                logger.info(
                    "[Scheduler] 软依赖跳过级联: page=%s (kind=%s) 移除对 %s 的依赖",
                    page_id, page_kind, failed_page_id,
                )
                continue

            blocked_now = await self._mark_page_failed_by_dependency(
                project_id=project_id,
                page_id=page.page_id,
                page_index=page.page_index,
                title=page.title or page.page_id,
                missing_dependencies=[failed_page_id],
                send_fn=send_fn,
            )
            for blocked_page_id in blocked_now:
                if blocked_page_id in blocked:
                    continue
                blocked.add(blocked_page_id)
                newly_failed.append(blocked_page_id)
                queue.extend(dependents.get(blocked_page_id, set()))

        return newly_failed

    async def _mark_page_failed_by_dependency(
        self,
        project_id: str,
        page_id: str,
        page_index: int,
        title: str,
        missing_dependencies: list[str],
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> list[str]:
        async with async_session() as dependency_session:
            pages = await deck_state_store.get_pages(dependency_session, project_id)
            target_page = next((page for page in pages if page.page_id == page_id), None)
            if not target_page or target_page.status == PageStatus.FAILED.value:
                return []

            reason = f"依赖页面不可用: {', '.join(missing_dependencies)}"
            logger.info(
                f"[Scheduler] page {target_page.page_id} cascade-failed "
                f"due to dependency failure on {missing_dependencies}"
            )
            await deck_state_store.update_page_status(
                dependency_session,
                target_page.id,
                PageStatus.FAILED.value,
            )
            await send_fn({
                "type": "webdeck_page_ready",
                "project_id": project_id,
                "page_id": target_page.page_id,
                "page_index": target_page.page_index,
                "title": target_page.title,
                "html": "",
                "status": "failed",
                "error": reason,
            })
            logger.warning(
                "[Scheduler] 页面依赖阻断: project=%s page=%s deps=%s",
                project_id,
                page_id,
                missing_dependencies,
            )
            return [page_id]

    async def _mark_unresolved_pages(
        self,
        project_id: str,
        unresolved_page_ids: list[str],
        pages_by_id: dict[str, Any],
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> list[str]:
        marked: list[str] = []
        for page_id in unresolved_page_ids:
            page = pages_by_id[page_id]
            marked.extend(await self._mark_page_failed_by_dependency(
                project_id=project_id,
                page_id=page.page_id,
                page_index=page.page_index,
                title=page.title or page.page_id,
                missing_dependencies=["循环依赖或未决依赖"],
                send_fn=send_fn,
            ))
        return marked
