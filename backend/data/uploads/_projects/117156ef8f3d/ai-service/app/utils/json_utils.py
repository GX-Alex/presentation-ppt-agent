"""从大模型响应文本中鲁棒提取 JSON（list 或 dict）。"""
import json
import re


def extract_json_raw(text: str) -> list | dict | None:
    """
    从可能含说明或代码块的文本中提取 JSON。
    策略：直接 loads → ```json/``` 块 → 首尾 {} → 首尾 []。
    返回 list | dict | None，解析失败返回 None。
    """
    if not text or not text.strip():
        return None
    cleaned = text.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for pattern in [r"```json\s*\n?(.*?)\n?\s*```", r"```\s*\n?(.*?)\n?\s*```"]:
        for m in re.findall(pattern, cleaned, re.DOTALL):
            try:
                return json.loads(m.strip())
            except json.JSONDecodeError:
                continue
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(cleaned[first_brace : last_brace + 1])
        except json.JSONDecodeError:
            pass
    first_bracket = cleaned.find("[")
    last_bracket = cleaned.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        try:
            return json.loads(cleaned[first_bracket : last_bracket + 1])
        except json.JSONDecodeError:
            pass
    return None
