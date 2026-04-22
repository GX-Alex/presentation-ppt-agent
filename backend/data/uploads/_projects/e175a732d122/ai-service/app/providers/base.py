"""
AI 模型调用抽象基类

定义所有 AI 模型适配器必须实现的接口规范，
确保不同提供商（百炼、私有化模型）可以无缝切换。

接口设计原则：
1. chat(): 纯文本输入输出 — 适用于文本型PDF的结构化解析和报告生成
2. vision(): 图片+文本输入 — 适用于扫描型PDF的图片识别
3. stream_chat(): 流式文本输出 — 适用于报告生成时的实时展示
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator


class AIProvider(ABC):
    """
    AI 模型调用抽象基类

    所有具体的 AI 模型适配器都必须继承此类并实现所有抽象方法。
    这保证了业务层代码（解析器、报告生成器）与具体的模型调用实现解耦，
    可以通过配置切换不同的模型提供商，而无需修改业务逻辑。
    """

    @abstractmethod
    async def chat(self, prompt: str, text: str) -> str:
        """
        调用文本模型

        用于文本型 PDF 的结构化解析和报告生成场景。
        将系统提示词（prompt）和用户输入文本（text）发送给大模型，
        返回模型的完整文本响应。

        参数：
            prompt: 系统提示词，定义模型的角色和输出格式要求
            text: 用户输入文本，即需要处理的银行流水文本内容

        返回：
            模型的完整文本响应（通常是 JSON 格式的解析结果）
        """
        pass

    @abstractmethod
    async def vision_multi(
        self, prompt: str, image_bytes_list: list[bytes], detail: str = "high"
    ) -> str:
        """
        调用多模态视觉模型（多图一次性传入）

        用于多文件/多页银行流水的一次性解析，将多张图片放入同一请求，
        减少调用次数、提升效率。模型需按 sourceIndex 返回分组结果。

        参数：
            prompt: 系统提示词（含多图解析说明）
            image_bytes_list: 多张 PNG 图片的二进制数据列表
            detail: 图片分辨率级别

        返回：
            模型响应，期望格式：[{"sourceIndex":0,"transactions":[...]},{"sourceIndex":1,...}]
        """
        pass

    @abstractmethod
    async def vision(
        self,
        prompt: str,
        image_bytes: bytes,
        detail: str = "high",
        mime_type: str = "image/png",
    ) -> str:
        """
        调用多模态视觉模型

        用于扫描型 PDF 的图片识别场景。
        将系统提示词（prompt）和页面图片（image_bytes）发送给视觉模型，
        模型会"看"图片并返回识别到的文本内容。

        参数：
            prompt: 系统提示词，定义模型的角色和输出格式要求
            image_bytes: 页面图片的二进制数据（PNG 或 JPEG）
            detail: 图片分辨率级别，"high" 为高清（默认），"low" 为低分辨率
            mime_type: 图片 MIME 类型，如 "image/png" 或 "image/jpeg"

        返回：
            模型的完整文本响应（通常是 JSON 格式的识别结果）
        """
        pass

    @abstractmethod
    async def stream_chat(self, prompt: str, text: str) -> AsyncGenerator[str, None]:
        """
        流式调用文本模型

        用于报告生成场景，实现打字机效果的实时输出。
        模型生成的内容会以流的方式逐步返回，前端可以实时展示，
        大幅提升用户体验（无需等待完整报告生成完毕）。

        参数：
            prompt: 系统提示词，定义报告的格式和要求
            text: 用户输入文本，即需要分析的数据内容

        生成：
            逐步产出模型响应的文本片段（chunk）
        """
        pass
