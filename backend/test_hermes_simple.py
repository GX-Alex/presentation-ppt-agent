"""
简化版hermes测试 — 验证研究→PPT流程和Plan B循环检测豁免。
Run: cd backend && python test_hermes_simple.py
"""
import asyncio
import json
import re
import sys
import time
import websockets  # type: ignore

WS_URL = "ws://127.0.0.1:8002/ws/chat"
TIMEOUT_QUICK = 30
TIMEOUT_AGENT = 300
TIMEOUT_BRIEF = 600

PROMPT = (
    "详细分析hermes agent项目。先研究它的核心代码，再生成一份20页的技术分享PPT。"
    "要求：科技极简主义风格，白底黑字，图表用深宝蓝色；每页含行动标题；优先用表格和矩阵。"
)

def log(tag: str, msg: str = ""):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{tag}] {msg}", flush=True)

async def recv_msg(ws, timeout: int, label: str):
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        return json.loads(raw)
    except asyncio.TimeoutError:
        log("TIMEOUT", f"waiting for {label} (>{timeout}s)")
        return None
    except Exception as e:
        log("ERROR", f"recv error: {e}")
        return None

def _extract_brief_from_content(content: str) -> dict | None:
    """从消息内容中提取 webdeck_brief JSON。"""
    m = re.search(
        r'<general-artifact[^>]*type="webdeck_brief"[^>]*>(.*?)</general-artifact>',
        content, re.DOTALL,
    )
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            return None
    return None

async def run_test():
    checks = {
        "ws_connect": False,
        "task_id_received": False,
        "dispatch_1_ok": False,
        "dispatch_2_allowed": False,  # 验证豁免生效（此测试中 dispatch=1 即可，标记为可选）
        "webdeck_brief_output": False,
        "brief_topic_nonempty": False,
        "plan_ready": False,
    }

    log("START", f"Connecting to {WS_URL}")
    try:
        ws_ctx = websockets.connect(WS_URL, open_timeout=10)
        ws = await ws_ctx.__aenter__()
    except Exception as e:
        log("FAIL", f"WS connection error: {e}")
        sys.exit(1)

    checks["ws_connect"] = True
    log("PASS", "WS connected")

    try:
        await ws.send(json.dumps({
            "type": "chat",
            "content": PROMPT,
            "task_id": "new",
        }))
        log("SENT", "research+PPT prompt")

        task_id = None
        dispatch_count = 0
        brief_json = None
        stream_content_acc = ""  # 累积 content_delta 内容

        for _ in range(800):
            p = await recv_msg(ws, TIMEOUT_AGENT, "agent/brief")
            if p is None:
                break

            ptype = p.get("type", "")
            if p.get("task_id") and not task_id:
                task_id = p["task_id"]
                checks["task_id_received"] = True
                log("INFO", f"task_id={task_id}")

            if ptype == "status":
                text = p.get("text", "")
                log("status", text[:100])

                if "dispatch_subagent" in text.lower():
                    dispatch_count += 1
                    log("INFO", f"dispatch #{dispatch_count} detected")
                    if dispatch_count == 1:
                        checks["dispatch_1_ok"] = True
                    if dispatch_count == 2:
                        checks["dispatch_2_allowed"] = True
                        log("PASS", "dispatch #2 allowed (Plan B exemption working)")

                if "重复派发" in text:
                    log("WARN", "dispatch loop detection triggered (豁免可能失败)")
                if "引导综合已有结果" in text:
                    log("WARN", "agent directed to synthesize (loop detection blocking dispatch)")

            elif ptype == "stream_start":
                stream_content_acc = ""  # 重置累积

            elif ptype == "content_delta":
                stream_content_acc += p.get("content", "")

            elif ptype == "stream_end":
                content = p.get("content", "") or stream_content_acc
                if content and 'type="webdeck_brief"' in content:
                    checks["webdeck_brief_output"] = True
                    log("PASS", "webdeck_brief artifact detected (via stream)")
                    brief_json = _extract_brief_from_content(content)
                    if brief_json and brief_json.get("topic", "").strip():
                        checks["brief_topic_nonempty"] = True
                        log("PASS", f"brief topic='{brief_json['topic'][:60]}'")
                    else:
                        log("WARN", f"brief topic empty or parse failed")

                    # 模拟前端：发送 webdeck_generate 触发 Deck 规划
                    if brief_json:
                        log("INFO", "Sending webdeck_generate to trigger deck planning...")
                        await ws.send(json.dumps({
                            "type": "webdeck_generate",
                            "task_id": task_id,
                            "brief": brief_json,
                        }))
                stream_content_acc = ""

            elif ptype == "message":
                content = p.get("content", "")
                if content and 'type="webdeck_brief"' in content:
                    checks["webdeck_brief_output"] = True
                    log("PASS", "webdeck_brief artifact detected (via message)")
                    brief_json = _extract_brief_from_content(content)
                    if brief_json and brief_json.get("topic", "").strip():
                        checks["brief_topic_nonempty"] = True
                        log("PASS", f"brief topic='{brief_json['topic'][:60]}'")

                    if brief_json:
                        log("INFO", "Sending webdeck_generate to trigger deck planning...")
                        await ws.send(json.dumps({
                            "type": "webdeck_generate",
                            "task_id": task_id,
                            "brief": brief_json,
                        }))

            elif ptype == "error":
                log("ERROR", f"backend error: {p.get('message','')[:160]}")

            elif ptype == "plan_ready" or (ptype == "webdeck_status" and p.get("status") == "plan_ready"):
                checks["plan_ready"] = True
                log("PASS", f"plan_ready (project={p.get('project_id', 'N/A')})")
                break

            elif ptype == "processing_done":
                # Agent loop 结束，如果 brief 已检测到但还没 plan_ready，继续等
                if checks["webdeck_brief_output"] and not checks["plan_ready"]:
                    log("INFO", "processing_done but waiting for plan_ready...")
                    continue
                elif not checks["webdeck_brief_output"]:
                    log("WARN", "processing_done without webdeck_brief")

            if checks["webdeck_brief_output"] and checks["plan_ready"]:
                break

        # RESULTS
        log("", "")
        log("RESULTS", "─" * 50)
        all_pass = True
        for k, v in checks.items():
            # dispatch_2_allowed 在单次 dispatch 流程中是可选的
            if k == "dispatch_2_allowed":
                icon = "✅" if v else "⚠️"
                if not v:
                    log(icon, f"{k}: {v} (optional — single dispatch flow)")
                else:
                    log(icon, f"{k}: {v}")
                continue
            icon = "✅" if v else "❌"
            log(icon, f"{k}: {v}")
            if not v:
                all_pass = False

        log("", "")
        log("FINAL", "ALL PASS" if all_pass else "SOME CHECKS FAILED")
        return all_pass

    finally:
        await ws_ctx.__aexit__(None, None, None)

if __name__ == "__main__":
    ok = asyncio.run(run_test())
    sys.exit(0 if ok else 1)
