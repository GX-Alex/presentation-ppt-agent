"""
AI 模型调用适配器模块

提供统一的 AI 模型调用接口，屏蔽不同模型提供商的差异：
- base.py: 抽象基类，定义统一接口规范
- bailian.py: 阿里云百炼平台适配器
- private.py: 私有化部署模型适配器（vLLM/Ollama）

通过工厂函数 get_provider() 根据配置自动选择合适的适配器。
"""

from app.providers.base import AIProvider
from app.providers.bailian import BailianProvider
from app.providers.private import PrivateProvider
from app.core.config import settings


def get_provider() -> AIProvider:
    """
    AI 模型提供商工厂函数

    根据配置文件中的 ai_provider 字段自动选择并创建对应的适配器实例。
    这是整个服务获取 AI 模型调用能力的统一入口。

    返回：
        AIProvider 实例（BailianProvider 或 PrivateProvider）

    异常：
        ValueError: 当 ai_provider 配置值不在支持列表中时抛出
    """
    if settings.ai_provider == "bailian":
        return BailianProvider()
    elif settings.ai_provider == "private":
        return PrivateProvider()
    else:
        raise ValueError(
            f"不支持的 AI 提供商: {settings.ai_provider}，"
            f"请在配置中设置 ai_provider 为 'bailian' 或 'private'"
        )


__all__ = ["AIProvider", "BailianProvider", "PrivateProvider", "get_provider"]
