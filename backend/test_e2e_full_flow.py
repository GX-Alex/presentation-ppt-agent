"""
Full end-to-end test for the quality PPT generation flow.
Tests: WS connect → intent detection → outline generation → duplicate-confirmation guard → rendering.
Run: python test_e2e_full_flow.py
"""
import asyncio
import json
import sys
import time

import websockets  # type: ignore


TIMEOUT_QUICK = 30    # seconds for quick responses
TIMEOUT_LLM   = 180  # seconds for LLM responses (outline gen: planner+reviewer+optional revision = up to ~3min)
TIMEOUT_RENDER = 180  # seconds for rendering to start producing slides


def log(tag: str, msg: str = ""):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] [{tag}] {msg}"
    print(line, flush=True)


async def recv_with_timeout(ws, timeout: int, label: str):
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        return json.loads(raw)
    except asyncio.TimeoutError:
        log("TIMEOUT", f"while waiting for {label} (>{timeout}s)")
        return None


async def e2e_test():
    results = {
        "ws_connect": False,
        "quality_entry_intent": False,
        "outline_generated": False,
        "render_started": False,
        "duplicate_blocked": False,
        "preview_update": False,
    }

    log("START", "Connecting to ws://127.0.0.1:8002/ws/chat")
    try:
        ws_ctx = websockets.connect("ws://127.0.0.1:8002/ws/chat", open_timeout=10)
        ws = await ws_ctx.__aenter__()
    except Exception as e:
        log("FAIL", f"WS connection error: {e}")
        sys.exit(1)

    results["ws_connect"] = True
    log("PASS", "WS connected")

    try:
        # ─────────────────────────────────────────────────────────────
        # STEP 1  Send initial chat → expect quality_entry intent
        # ─────────────────────────────────────────────────────────────
        await ws.send(json.dumps({
            "type": "chat",
            "content": "请帮我做一个银行数字化转型PPT，给管理层汇报",
            "task_id": "new"
        }))
        log("SENT", "initial chat message")

        task_id = None
        for _ in range(20):
            p = await recv_with_timeout(ws, TIMEOUT_QUICK, "quality_entry")
            if p is None:
                break
            ptype = p.get("type")
            if p.get("task_id") and not task_id:
                task_id = p["task_id"]
                log("INFO", f"task_id={task_id}")
            if ptype == "status":
                log("status", p.get("text", "")[:100])
            elif ptype == "message" and p.get("message_type") == "quality_entry":
                results["quality_entry_intent"] = True
                log("PASS", "quality_entry intent detected")
                break
            elif ptype == "error":
                log("FAIL", f"backend error: {p.get('text','')[:120]}")
                sys.exit(1)

        if not results["quality_entry_intent"]:
            log("FAIL", "quality_entry intent never received")
            sys.exit(1)
        if not task_id:
            log("FAIL", "no task_id received")
            sys.exit(1)

        # ─────────────────────────────────────────────────────────────
        # STEP 2  Send quality brief → expect outline
        # ─────────────────────────────────────────────────────────────
        brief = {
            "title": "银行数字化转型战略汇报",
            "topic": "银行数字化转型",
            "audience": "管理层",
            "goal": "讲清楚现状、风险和建议",
            "deliverable": "ppt",
            "slide_count": 5,
            "main_slide_count": 4,
            "appendix_slide_count": 1,
            "theme_id": "tech_dark",
            "tone": "专业、克制",
            "must_include": ["现状判断", "关键风险", "行动建议"],
            "appendix": True,
            "notes": "",
            "attachments": [],
            "reference_urls": [],
        }
        await ws.send(json.dumps({"type": "quality_generate", "brief": brief, "task_id": task_id}))
        log("SENT", "quality brief")

        for _ in range(60):
            p = await recv_with_timeout(ws, TIMEOUT_LLM, "outline")
            if p is None:
                break
            ptype = p.get("type")
            if ptype == "status":
                log("status", p.get("text", "")[:100])
            elif ptype == "error":
                log("FAIL", f"backend error during brief: {p.get('text','')[:120]}")
                sys.exit(1)
            elif ptype == "outline":
                slides = p.get("slides", [])
                results["outline_generated"] = True
                log("PASS", f"outline received — {len(slides)} slides")
                for s in slides:
                    log("slide", f"  {s.get('title','?')}")
                break
            elif ptype == "message":
                log("msg", f"[{p.get('message_type')}] {str(p.get('content',''))[:80]}")

        if not results["outline_generated"]:
            log("FAIL", "outline never received")
            sys.exit(1)

        # ─────────────────────────────────────────────────────────────
        # STEP 3  Send FIRST confirmation, then IMMEDIATE DUPLICATE
        # ─────────────────────────────────────────────────────────────
        await ws.send(json.dumps({
            "type": "chat",
            "content": "好的，确认，开始生成幻灯片",
            "task_id": task_id,
        }))
        log("SENT", "FIRST confirmation")

        await asyncio.sleep(0.5)  # simulate slight user delay then re-click

        await ws.send(json.dumps({
            "type": "chat",
            "content": "好的，确认，开始生成幻灯片",
            "task_id": task_id,
        }))
        log("SENT", "DUPLICATE confirmation (should be blocked)")

        # ─────────────────────────────────────────────────────────────
        # STEP 4  Collect render-phase events
        # ─────────────────────────────────────────────────────────────
        render_kw = ["渲染", "正在生成", "构建", "生成幻灯片", "幻灯片仍在生成中", "请勿重复确认", "准备", "已写入", "推送"]
        duplicate_blocked_kw = ["请勿重复确认", "仍在生成中", "已生成完毕", "如需重新生成"]
        for i in range(80):
            p = await recv_with_timeout(ws, TIMEOUT_RENDER, f"render event {i}")
            if p is None:
                log("WARN", "render phase timed out (LLM may be slow)")
                break
            ptype = p.get("type")
            text  = str(p.get("text", p.get("content", "")))

            if ptype == "status":
                log(f"render[{i}]", text[:120])
                if any(k in text for k in render_kw):
                    results["render_started"] = True
                if any(k in text for k in duplicate_blocked_kw):
                    results["duplicate_blocked"] = True
                    log("PASS", "duplicate confirmation blocked!")

            elif ptype == "preview_update":
                slides = p.get("slides", [])
                log("PASS", f"preview_update received — {len(slides)} slides delivered")
                results["preview_update"] = True
                break

            elif ptype == "slide_ready":
                idx = p.get("index", "?")
                log(f"slide_ready[{i}]", f"slide index={idx} delivered")
                results["preview_update"] = True
                # don't break — keep collecting until ppt_completed

            elif ptype == "ppt_completed":
                sc = p.get("slide_count", "?")
                log("PASS", f"ppt_completed — {sc} slides total")
                results["preview_update"] = True
                # drain a few more messages to catch any late duplicate-guard status
                for _ in range(5):
                    extra = await recv_with_timeout(ws, 3, "post-complete drain")
                    if extra is None:
                        break
                    etype = extra.get("type")
                    etext = str(extra.get("text", extra.get("content", "")))
                    if etype == "status":
                        log("drain", etext[:120])
                        if any(k in etext for k in duplicate_blocked_kw):
                            results["duplicate_blocked"] = True
                            log("PASS", "duplicate confirmation blocked (post-complete)!")
                break

            elif ptype == "error":
                log("FAIL", f"backend error during render: {text[:120]}")
                break

            elif ptype == "message":
                log(f"msg[{i}]", f"[{p.get('message_type')}] {text[:80]}")

    finally:
        await ws_ctx.__aexit__(None, None, None)

    # ─────────────────────────────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60, flush=True)
    print("E2E TEST SUMMARY", flush=True)
    print("=" * 60, flush=True)
    for key, ok in results.items():
        icon = "✓" if ok else "✗"
        status = "PASS" if ok else "FAIL / NOT REACHED"
        print(f"  {icon} {key:<30} {status}", flush=True)

    critical = results["ws_connect"] and results["quality_entry_intent"] and results["outline_generated"]
    print("", flush=True)
    if critical:
        print("[RESULT] Critical path PASSED", flush=True)
    else:
        print("[RESULT] CRITICAL PATH FAILED", flush=True)
        sys.exit(1)


asyncio.run(e2e_test())
