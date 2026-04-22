"""Sprint 4 验证测试脚本"""
import sys
print(f"Python: {sys.version}")
print()

# 1. skill_service
from app.services.skill_service import (
    load_system_skills, get_system_skill_list, get_skill_menu,
    SYSTEM_SKILLS, list_user_skills, create_user_skill,
    validate_user_skill, toggle_user_skill, get_enabled_user_skills
)
print(f"✅ skill_service 导入成功, 系统Skill数: {len(SYSTEM_SKILLS)}")

# 2. memory_service
from app.services.memory_service import (
    compute_embedding, cosine_similarity, detect_memory_signals,
    capture_memory, search_memories, save_checkpoint
)
print("✅ memory_service 导入成功")

# 3. context_service
from app.services.context_service import (
    count_tokens, count_messages_tokens, assemble_context,
    compress_context, handle_compact_command, get_token_budget_info,
    MODEL_CONTEXT_WINDOW, COMPRESS_THRESHOLD
)
print(f"✅ context_service 导入成功 窗口={MODEL_CONTEXT_WINDOW} 阈值={COMPRESS_THRESHOLD}")

# 4. load_skill tool
from app.tools.load_skill import TOOL_DEFINITION, execute
print(f"✅ load_skill 工具导入成功 名称={TOOL_DEFINITION['function']['name']}")

# 5. agent_loop
from app.core.agent_loop import agent_loop, SYSTEM_PROMPT, DEFAULT_USER_ID
print("✅ agent_loop 导入成功")

# 6. llm_client
from app.core.llm_client import chat, LLMResponse, get_task_token_stats
print("✅ llm_client 导入成功")

# 7. skills API
from app.api.skills import router
print(f"✅ skills API 导入成功, 路由数={len(router.routes)}")

# 8. chat_handler
from app.ws.chat_handler import router as ws_router
print("✅ chat_handler 导入成功")

# 9. 系统 Skill 加载
load_system_skills()
skill_list = get_system_skill_list()
names = [s["name"] for s in skill_list]
print(f"✅ 系统 Skill 加载: {names}")

# 10. Skill 菜单
menu = get_skill_menu()
print(f"✅ Skill 菜单: {len(menu)} 字符")

# 11. 记忆信号检测
signals = detect_memory_signals("我喜欢用暗色主题")
print(f"✅ 记忆信号(偏好): {signals}")

signals2 = detect_memory_signals("我是张三, 来自北京")
print(f"✅ 记忆信号(事实): {signals2}")

signals3 = detect_memory_signals("今天天气不错")
print(f"✅ 记忆信号(无): {signals3}")

# 12. Token 计数
tc = count_tokens("Hello, 你好世界")
print(f"✅ Token 计数: {tc} tokens")

# 13. Token 预算
budget = get_token_budget_info()
print(f"✅ Token 预算: {budget}")

# 14. Tool 自动发现
from app.core.tool_dispatch import auto_discover_tools, get_tool_names
auto_discover_tools()
tools = get_tool_names()
print(f"✅ Tool 发现: {tools}")
assert "load_skill" in tools, "load_skill 未注册!"

# 15. cosine similarity
v1 = [1.0, 0.0, 0.0]
v2 = [0.0, 1.0, 0.0]
v3 = [1.0, 0.0, 0.0]
sim12 = cosine_similarity(v1, v2)
sim13 = cosine_similarity(v1, v3)
print(f"✅ 余弦相似度: orthogonal={sim12:.2f}, identical={sim13:.2f}")
assert sim12 == 0.0
assert sim13 == 1.0

print()
print("=" * 50)
print("所有 Python 导入和基础功能测试通过! ✅")
