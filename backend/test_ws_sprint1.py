"""Sprint 1 WebSocket 端到端测试脚本。"""
import asyncio
import json
import os
import sys

# 清除代理环境变量
for key in ["ALL_PROXY", "all_proxy", "SOCKS_PROXY", "socks_proxy",
            "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"]:
    os.environ.pop(key, None)

import websockets


async def test_chat():
    """测试基本对话流程。"""
    print("=" * 50)
    print("测试 1: 基本对话")
    print("=" * 50)

    uri = "ws://localhost:8000/ws/chat"
    async with websockets.connect(uri, proxy=None) as ws:
        # 发送聊天消息
        await ws.send(json.dumps({
            "type": "chat",
            "content": "你好，请用一句话介绍你自己",
            "task_id": "new",
        }))

        task_id = None
        msgs = []
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(raw)
                msgs.append(data)
                msg_type = data.get("type", "")
                print(f"  [{msg_type}] {json.dumps(data, ensure_ascii=False)[:150]}")

                if msg_type == "task_info":
                    task_id = data.get("task_id")

                if msg_type == "message" and data.get("role") == "assistant":
                    break
        except asyncio.TimeoutError:
            print("  ⏰ 超时!")

        print(f"\n  ✅ 共收到 {len(msgs)} 条消息, task_id={task_id}")
        return task_id


async def test_history_restore(task_id: str):
    """测试历史消息恢复 (REST API)。"""
    print("\n" + "=" * 50)
    print(f"测试 2: 历史消息恢复 (task_id={task_id[:8]}...)")
    print("=" * 50)

    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://localhost:8000/api/tasks/{task_id}")
        data = resp.json()

        if data.get("error"):
            print(f"  ❌ 获取任务失败: {data['error']}")
            return False

        messages = data.get("messages", [])
        print(f"  任务标题: {data.get('title')}")
        print(f"  消息数量: {len(messages)}")
        for m in messages:
            role = m.get("role")
            content = (m.get("content") or "")[:80]
            print(f"    [{role}] {content}")

        if len(messages) >= 2:
            print("  ✅ 历史消息恢复成功!")
            return True
        else:
            print("  ❌ 历史消息不完整")
            return False


async def test_task_list():
    """测试任务列表 API。"""
    print("\n" + "=" * 50)
    print("测试 3: 任务列表 API")
    print("=" * 50)

    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get("http://localhost:8000/api/tasks/")
        data = resp.json()
        tasks = data.get("tasks", [])
        print(f"  任务数量: {len(tasks)}")
        for t in tasks:
            print(f"    [{t['status']}] {t['title']} (id={t['id'][:8]}...)")

        if len(tasks) >= 1:
            print("  ✅ 任务列表正常!")
            return True
        else:
            print("  ❌ 任务列表为空")
            return False


async def main():
    print("\n🚀 Sprint 1 端到端验证测试\n")

    # 测试 1: 基本对话
    task_id = await test_chat()
    if not task_id:
        print("\n❌ 基本对话测试失败，中止后续测试")
        sys.exit(1)

    # 测试 2: 历史恢复
    ok2 = await test_history_restore(task_id)

    # 测试 3: 任务列表
    ok3 = await test_task_list()

    # 汇总
    print("\n" + "=" * 50)
    print("测试汇总")
    print("=" * 50)
    print(f"  基本对话:     ✅")
    print(f"  历史恢复:     {'✅' if ok2 else '❌'}")
    print(f"  任务列表:     {'✅' if ok3 else '❌'}")
    all_pass = ok2 and ok3
    print(f"\n{'🎉 全部通过!' if all_pass else '⚠️ 部分失败'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    asyncio.run(main())
