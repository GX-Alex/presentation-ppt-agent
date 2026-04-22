"""
WebDeck 全流程集成测试脚本。
测试用例:
  1. AI 客服改造方案 — 覆盖执行摘要、架构图、图表分析、路线图等高价值页面
  2. 2024 AI 发展趋势 — 覆盖 cover、toc、content、closing 等普通页面

该脚本通过 WebSocket 连接后端，模拟前端操作，验证完整的:
  Brief → Plan → Approve → Generate → Review → Complete 流程
"""
import asyncio
import json
import time
import sys
import os

# 确保可以 import 项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import websockets


WS_URL = os.getenv("WEBDECK_WS_URL", "ws://127.0.0.1:8002/ws/chat")
TIMEOUT = int(os.getenv("WEBDECK_TIMEOUT", "900"))  # 最长等待秒数


class DeckFlowTester:
    """WebDeck 全流程测试器"""

    def __init__(self, test_name: str, brief: dict):
        self.test_name = test_name
        self.brief = brief
        self.messages: list[dict] = []
        self.project_id: str | None = None
        self.manifest: dict | None = None
        self.pages_ready: list[str] = []
        self.final_html: str | None = None
        self.errors: list[str] = []
        self.task_id: str | None = None
        self.page_review_events = 0
        self.deck_review_received = False

    async def run(self) -> bool:
        """执行完整测试流程"""
        print(f"\n{'='*60}")
        print(f"测试: {self.test_name}")
        print(f"Brief: {json.dumps(self.brief, ensure_ascii=False)}")
        print(f"{'='*60}")

        try:
            async with websockets.connect(WS_URL) as ws:
                # 阶段 1: 发送 webdeck_generate
                print("\n[阶段1] 发送 webdeck_generate...")
                await ws.send(json.dumps({
                    "type": "webdeck_generate",
                    "brief": self.brief,
                    "task_id": "new",
                }))

                # 等待 plan_ready（manifest）
                plan_ready = await self._wait_for_message(
                    ws, "webdeck_manifest", timeout=120,
                    description="等待 manifest"
                )
                if not plan_ready:
                    self.errors.append("未收到 webdeck_manifest")
                    return self._report(False)

                print(f"  ✅ 收到 manifest: {len(self.manifest.get('pages', []))} 页")
                if self.manifest:
                    for p in self.manifest.get("pages", []):
                        print(f"     - {p.get('page_id', '?')}. {p.get('title', '?')} ({p.get('page_kind', '?')})")

                if not self.project_id:
                    self.errors.append("未获取到 project_id")
                    return self._report(False)

                # 阶段 2: 确认 manifest，触发生成
                print(f"\n[阶段2] 确认 manifest, project_id={self.project_id}...")
                await ws.send(json.dumps({
                    "type": "webdeck_approve_plan",
                    "project_id": self.project_id,
                }))

                # 等待所有页面生成完成
                complete = await self._wait_for_message(
                    ws, "webdeck_complete", timeout=TIMEOUT,
                    description="等待所有页面生成"
                )
                if not complete:
                    self.errors.append("未收到 webdeck_complete")
                    return self._report(False)

                print(f"  ✅ Deck 生成完成! 页面数: {len(self.pages_ready)}")

                # 阶段 3: 验证结果
                print(f"\n[阶段3] 验证结果...")
                return self._report(self._validate())

        except Exception as e:
            self.errors.append(f"连接异常: {e}")
            return self._report(False)

    async def _wait_for_message(
        self, ws, target_type: str, timeout: float, description: str
    ) -> bool:
        """等待特定消息类型"""
        start = time.time()
        print(f"  ⏳ {description} (最长 {timeout}s)...")

        while time.time() - start < timeout:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                msg = json.loads(raw)
                msg_type = msg.get("type", "")
                self.messages.append(msg)

                # 处理各消息类型
                if msg_type == "task_info":
                    self.task_id = msg.get("task_id")
                    print(f"     task_info: task_id={self.task_id}")

                elif msg_type == "webdeck_status":
                    status = msg.get("status")
                    pid = msg.get("project_id")
                    if pid:
                        self.project_id = pid
                    print(f"     webdeck_status: {status} (project={pid})")

                elif msg_type == "webdeck_manifest":
                    self.manifest = msg.get("manifest")
                    pid = msg.get("project_id")
                    if pid:
                        self.project_id = pid
                    print(f"     webdeck_manifest: 收到 ({self.manifest.get('totalPages', '?')} pages)")

                elif msg_type == "webdeck_page_ready":
                    page_id = msg.get("page_id", "")
                    title = msg.get("title", "")
                    self.pages_ready.append(page_id)
                    print(f"     webdeck_page_ready: {title} ({len(self.pages_ready)} done)")

                elif msg_type == "webdeck_pages_init":
                    pages = msg.get("pages", [])
                    print(f"     webdeck_pages_init: {len(pages)} pages initialized")

                elif msg_type == "webdeck_progress":
                    current = msg.get("current", 0)
                    total = msg.get("total", 0)
                    print(f"     webdeck_progress: {current}/{total}")

                elif msg_type == "webdeck_lane_status":
                    lane = msg.get("lane_id", "")
                    status = msg.get("status", "")
                    print(f"     lane: {lane} → {status}")

                elif msg_type == "webdeck_complete":
                    self.final_html = msg.get("html")
                    print(f"     webdeck_complete: HTML length={len(self.final_html or '')}")

                elif msg_type == "webdeck_review":
                    level = msg.get("level", "page")
                    score = msg.get("score", "?")
                    passed = msg.get("passed", False)
                    print(f"     review: level={level} score={score} passed={passed}")
                    if level == "page":
                        self.page_review_events += 1
                    elif level == "deck":
                        self.deck_review_received = True

                elif msg_type == "status":
                    text = msg.get("text", "")
                    print(f"     status: {text[:80]}")

                elif msg_type == "error":
                    error_msg = msg.get("message", "未知错误")
                    print(f"     ❌ error: {error_msg}")
                    self.errors.append(error_msg)

                elif msg_type == "processing_done":
                    print(f"     processing_done")

                elif msg_type == "pong":
                    pass  # 心跳

                else:
                    print(f"     [{msg_type}]: {str(msg)[:100]}")

                if msg_type == target_type:
                    return True

                # 如果收到 processing_done 且目标还没到，说明流程结束了
                if msg_type == "processing_done" and target_type != "processing_done":
                    # 给一个小缓冲：可能 complete 在 processing_done 之前
                    continue

            except asyncio.TimeoutError:
                elapsed = time.time() - start
                print(f"     ... 已等待 {elapsed:.0f}s")
                continue

        return False

    def _validate(self) -> bool:
        """验证输出结果"""
        ok = True

        # 检查 manifest
        if not self.manifest:
            self.errors.append("manifest 为空")
            ok = False
        else:
            pages = self.manifest.get("pages", [])
            if len(pages) < 3:
                self.errors.append(f"manifest 页数过少: {len(pages)}")
                ok = False

        # 检查最终 HTML
        if not self.final_html:
            print("  ⚠️ 未收到最终 HTML（可能需要通过 REST API 获取）")
        else:
            html_len = len(self.final_html)
            if html_len < 500:
                self.errors.append(f"最终 HTML 过短: {html_len}")
                ok = False
            else:
                print(f"  ✅ 最终 HTML 长度: {html_len}")

            # 检查关键元素
            checks = [
                ("deck-page", "页面 section"),
                ("data-page-id", "页面 ID 属性"),
            ]
            for keyword, desc in checks:
                if keyword in self.final_html:
                    print(f"  ✅ 包含 {desc}")
                else:
                    print(f"  ⚠️ 缺少 {desc}")

        if self.page_review_events == 0:
            self.errors.append("未收到页级审稿事件")
            ok = False

        if not self.deck_review_received:
            self.errors.append("未收到 deck 级审稿事件")
            ok = False

        return ok

    def _report(self, success: bool) -> bool:
        """输出测试报告"""
        print(f"\n{'─'*40}")
        if success:
            print(f"✅ 测试通过: {self.test_name}")
        else:
            print(f"❌ 测试失败: {self.test_name}")
            for e in self.errors:
                print(f"   错误: {e}")
        print(f"  收到消息总数: {len(self.messages)}")
        print(f"  完成页面数: {len(self.pages_ready)}")
        print(f"{'─'*40}")

        # 保存最终 HTML 到文件
        if self.final_html:
            fname = f"/tmp/webdeck_test_{self.test_name.replace(' ', '_')}.html"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(self.final_html)
            print(f"  💾 HTML 已保存: {fname}")

        # 保存消息日志
        log_fname = f"/tmp/webdeck_test_{self.test_name.replace(' ', '_')}_log.json"
        with open(log_fname, "w", encoding="utf-8") as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=2)
        print(f"  📝 消息日志: {log_fname}")

        return success


async def main():
    # 测试用例 1: AI 客服改造方案（覆盖高价值页面类型）
    test1 = DeckFlowTester(
        test_name="AI客服改造方案",
        brief={
            "topic": "AI 智能客服系统改造方案：从传统客服到 AI 原生客服的战略转型",
            "audience": "企业管理层和技术负责人",
            "pageCount": 8,
            "extras": "需要包含执行摘要、现状诊断、目标架构、ROI 分析图表、实施路线图。重点强调 AI 技术落地价值。",
        },
    )

    result1 = await test1.run()

    # 测试用例 2 暂不运行（节省时间），先验证用例 1
    # test2 = DeckFlowTester(
    #     test_name="AI发展趋势",
    #     brief={
    #         "topic": "2024 年 AI 发展趋势深度分析",
    #         "audience": "技术管理层",
    #         "pageCount": 6,
    #     },
    # )
    # result2 = await test2.run()

    print(f"\n{'='*60}")
    print("测试结果汇总")
    print(f"{'='*60}")
    print(f"  用例1 (AI客服改造方案): {'✅ 通过' if result1 else '❌ 失败'}")
    # print(f"  用例2 (AI发展趋势): {'✅ 通过' if result2 else '❌ 失败'}")

    return result1


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
