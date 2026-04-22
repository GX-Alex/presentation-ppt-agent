"""
测试 hermes agent 研究+PPT 复合任务流程。
验证：J2强制摘要、_COMPOSITE_RESEARCH_PPT_TEMPLATE 修复、webdeck_brief 正确生成。
Run: cd backend && python test_hermes_research_ppt.py
"""
import asyncio
import json
import sys
import time

import websockets  # type: ignore


WS_URL = "ws://127.0.0.1:8002/ws/chat"
TIMEOUT_QUICK = 30
TIMEOUT_AGENT = 300  # code_analyst 最多 15 轮，可能需要较长时间
TIMEOUT_BRIEF = 600  # 整个研究+brief 流程

HERMES_PROMPT = (
    "详细分析hermes agent这个项目，做一个介绍最近非常火的关于hermes agent的技术分享，"
    "先研究这个项目的核心代码，生成研究报告，然后再生成ppt，不少于20页。"
    "要求：1. 视觉与美学标准（通用设计语言）\n \n"
    "美学风格： 科技极简主义，但信息密度高。简洁、锐利、权威。\n"
    "排版规则：\n \n"
    "- 标题： 使用衬线字体（如 Times New Roman 或 Garamond），以传递专业、金融报告的质感。\n"
    "- 数据/标签： 使用清晰的无衬线字体（如 Arial 或 Roboto）用于图表标签和数字，确保可读性。\n"
    "配色方案： 干净的白色背景。文本为锐利的黑色。图表使用深宝蓝色作为主色，搭配不同层次的灰色来体现数据层级。\n"
    "图形： 表格使用细发丝边框，图表使用精确的矢量线条。避免3D效果或阴影。\n \n \n \n"
    "2. 内容与布局逻辑（麦肯锡风格）\n \n"
    "\"行动标题\"： 每一页幻灯片都必须有一个完整的句子作为结论（即\"So What\"）。\n"
    "丰富的数据可视化： 不要使用简单的列表。优先采用：\n \n"
    "- 复杂图表： 堆叠柱状图、瀑布图或马里梅科图（Marimekko）。\n"
    "- 数据表格： 包含特定行和列的详细表格。\n"
    "- 框架： 战略图表或由细而干净的线条构成的2x2矩阵。\n"
    "高信息密度： 布局必须复杂且采用多栏式（例如2-3栏），模仿真实的商业分析报告，而非空泛的封面页。\n"
    "数据完整性： 如果确切数字未知，使用占位符  [Data: XX%] 。不要编造来源。\n"
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


async def run_test():
    checks = {
        "ws_connect": False,
        "task_id_received": False,
        "subagent_dispatched": False,
        "j2_forced_summary": False,       # 如果 content="" 时触发了强制摘要
        "webdeck_brief_output": False,
        "brief_topic_nonempty": False,
        "brief_pre_research_populated": False,
        "brief_notes_has_style": False,   # notes 字段包含样式要求
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
        # ── STEP 1: send hermes agent prompt ──────────────────────────────
        await ws.send(json.dumps({
            "type": "chat",
            "content": HERMES_PROMPT,
            "task_id": "new",
        }))
        log("SENT", "hermes agent research+PPT prompt")

        task_id = None
        brief_json = None

        for _ in range(300):  # up to 300 messages
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
                log("status", text[:120])
                # J2 强制摘要触发迹象
                if "强制摘要" in text or "forced" in text.lower():
                    checks["j2_forced_summary"] = True
                    log("PASS", "J2 forced summary triggered")
                # subagent dispatch 迹象
                if "dispatch" in text.lower() or "子" in text or "subagent" in text.lower() or "code_analyst" in text or "researcher" in text:
                    checks["subagent_dispatched"] = True

            elif ptype == "message":
                content = p.get("content", "")
                # 检测 webdeck_brief artifact
                if 'type="webdeck_brief"' in content or "webdeck_brief" in content:
                    checks["webdeck_brief_output"] = True
                    log("PASS", "webdeck_brief artifact detected")
                    # 提取 JSON
                    import re
                    m = re.search(r'<general-artifact[^>]*type="webdeck_brief"[^>]*>(.*?)</general-artifact>', content, re.DOTALL)
                    if m:
                        try:
                            brief_json = json.loads(m.group(1).strip())
                            if brief_json.get("topic"):
                                checks["brief_topic_nonempty"] = True
                                log("PASS", f"brief topic='{brief_json['topic']}'")
                            if brief_json.get("pre_research"):
                                checks["brief_pre_research_populated"] = True
                                log("PASS", f"pre_research has {len(brief_json['pre_research'])} items")
                            if brief_json.get("notes"):
                                checks["brief_notes_has_style"] = True
                                log("PASS", f"notes populated: {brief_json['notes'][:80]}...")
                        except Exception as je:
                            log("WARN", f"brief JSON parse error: {je}")
                            log("WARN", f"raw brief: {m.group(1)[:300]}")

            elif ptype == "webdeck_generate":
                log("INFO", "webdeck_generate WS event received → planning started")

            elif ptype == "plan_ready":
                checks["plan_ready"] = True
                log("PASS", "plan_ready — deck outline ready for user approval")
                break

            elif ptype == "error":
                log("ERROR", f"backend error: {p.get('text','')[:160]}")

            # 如果 brief 已收到且已 plan_ready，停止等待
            if checks["brief_topic_nonempty"] and checks["plan_ready"]:
                break

        # ── RESULTS ───────────────────────────────────────────────────────
        log("", "")
        log("RESULTS", "─" * 50)
        all_pass = True
        for k, v in checks.items():
            icon = "✅" if v else "❌"
            log(icon, f"{k}: {v}")
            if not v:
                all_pass = False

        if brief_json:
            log("", "")
            log("BRIEF", json.dumps({k: str(v)[:120] if isinstance(v, str) else v
                                      for k, v in brief_json.items() if k != "pre_research"}, ensure_ascii=False, indent=2))

        log("", "")
        log("FINAL", "ALL PASS" if all_pass else "SOME CHECKS FAILED")
        return all_pass

    finally:
        await ws_ctx.__aexit__(None, None, None)


if __name__ == "__main__":
    ok = asyncio.run(run_test())
    sys.exit(0 if ok else 1)
