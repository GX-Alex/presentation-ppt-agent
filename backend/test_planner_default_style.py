from app.services.webdeck_runtime.planner import DeckPlanner, DEFAULT_DESIGN_STYLE

def test_uses_default_style_when_notes_empty():
    planner = DeckPlanner()
    brief = {"topic": "测试主题", "page_count": 5}
    prompt = planner._build_planning_prompt(brief)
    assert "设计风格要求" in prompt
    assert "Times New Roman" in prompt
    assert "麦肯锡" in prompt

def test_uses_user_style_when_notes_provided():
    planner = DeckPlanner()
    brief = {"topic": "测试主题", "page_count": 5, "notes": "极简黑白风格，禁止任何蓝色"}
    prompt = planner._build_planning_prompt(brief)
    assert "极简黑白风格" in prompt
    assert "Times New Roman" not in prompt  # default not injected when user style provided

def test_default_style_constant_exported():
    assert "Times New Roman" in DEFAULT_DESIGN_STYLE
    assert "#0A2463" in DEFAULT_DESIGN_STYLE
    assert "So What" in DEFAULT_DESIGN_STYLE

def test_uses_default_style_when_notes_empty_string():
    planner = DeckPlanner()
    brief = {"topic": "测试主题", "page_count": 5, "notes": ""}
    prompt = planner._build_planning_prompt(brief)
    assert "Times New Roman" in prompt  # default injected for empty string notes

def test_uses_default_style_when_notes_whitespace():
    planner = DeckPlanner()
    brief = {"topic": "测试主题", "page_count": 5, "notes": "   "}
    prompt = planner._build_planning_prompt(brief)
    assert "Times New Roman" in prompt  # default injected for whitespace-only notes

def test_does_not_crash_when_notes_is_dict():
    planner = DeckPlanner()
    brief = {"topic": "测试主题", "page_count": 5, "notes": {"style": "custom"}}
    prompt = planner._build_planning_prompt(brief)
    assert "设计风格要求" in prompt  # no crash, some style injected
