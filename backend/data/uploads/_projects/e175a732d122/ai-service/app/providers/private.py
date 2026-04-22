"""
私有化部署模型适配器

通过 OpenAI 兼容接口调用私有化部署的大模型（vLLM / Ollama 等推理框架）。
私有化部署的模型运行在本地或内网服务器上，适合对数据安全要求较高的场景。

与百炼适配器的核心区别：
1. 端点地址指向私有化服务（如 http://localhost:8001/v1）
2. API Key 可能为空或使用自定义认证
3. 模型名称对应私有化部署的模型（如 Qwen2.5-VL-7B-Instruct）

重试策略：与百炼适配器相同，最多重试 3 次
"""

import base64
import logging
import time
from typing import AsyncGenerator

from openai import AsyncOpenAI

from app.core.config import settings
from app.providers.base import AIProvider

# 模块级日志器
logger = logging.getLogger(__name__)

# 最大重试次数
MAX_RETRIES = 3
# 重试间隔基数（秒），使用指数退避策略
RETRY_DELAY_BASE = 1.0


class PrivateProvider(AIProvider):
    """
    私有化部署模型适配器

    通过 OpenAI 兼容接口调用本地或内网部署的大模型推理服务。
    支持 vLLM、Ollama、TGI 等兼容 OpenAI 接口的推理框架。
    """

    def __init__(self):
        """
        初始化私有化模型适配器

        创建 AsyncOpenAI 客户端实例，指向私有化模型的 API 端点。
        私有化部署通常不需要 API Key，使用占位符 "not-needed" 即可。
        """
        self.client = AsyncOpenAI(
            api_key="not-needed",  # 私有化部署通常无需 API Key 认证
            base_url=settings.private_endpoint,
        )
        self.text_model = settings.private_text_model
        self.vl_model = settings.private_vl_model
        logger.info(
            "私有化模型适配器初始化完成 — 端点: %s, 文本模型: %s, 视觉模型: %s",
            settings.private_endpoint,
            self.text_model,
            self.vl_model,
        )

    async def chat(self, prompt: str, text: str) -> str:
        """
        调用私有化文本模型

        使用 OpenAI 兼容接口调用本地部署的文本模型，
        适用于文本型 PDF 的结构化解析和报告生成。

        参数：
            prompt: 系统提示词（定义角色和输出格式）
            text: 待处理的文本内容

        返回：
            模型的完整文本响应

        异常：
            Exception: 所有重试均失败后抛出最后一次的异常
        """
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ]

        logger.info("[provider:private] chat 调用提示词 | prompt_len=%d | text_len=%d\n--- prompt ---\n%s\n--- user text (前500字) ---\n%s\n---", len(prompt), len(text), prompt, text[:500] + ("..." if len(text) > 500 else ""))

        last_exception = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    "私有化文本模型调用开始 — 模型: %s, 第 %d/%d 次尝试, 文本长度: %d",
                    self.text_model, attempt, MAX_RETRIES, len(text),
                )
                start_time = time.time()

                response = await self.client.chat.completions.create(
                    model=self.text_model,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=settings.max_output_tokens,
                    timeout=settings.parse_timeout,
                )

                elapsed = time.time() - start_time
                result = response.choices[0].message.content

                # 私有化模型的 usage 信息可能不完整，做兼容处理
                usage = response.usage
                logger.info(
                    "私有化文本模型调用成功 — 耗时: %.2f秒, "
                    "输入token: %s, 输出token: %s, 总token: %s",
                    elapsed,
                    usage.prompt_tokens if usage else "N/A",
                    usage.completion_tokens if usage else "N/A",
                    usage.total_tokens if usage else "N/A",
                )
                return result

            except Exception as e:
                last_exception = e
                logger.warning(
                    "私有化文本模型调用失败 — 第 %d/%d 次, 错误: %s",
                    attempt, MAX_RETRIES, str(e),
                )
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    logger.info("等待 %.1f 秒后重试...", delay)
                    import asyncio
                    await asyncio.sleep(delay)

        logger.error("私有化文本模型调用最终失败，已重试 %d 次", MAX_RETRIES)
        raise last_exception

    async def vision(
        self,
        prompt: str,
        image_bytes: bytes,
        detail: str = "high",
        mime_type: str = "image/png",
    ) -> str:
        """
        调用私有化多模态视觉模型

        将页面图片编码为 base64 后，调用本地部署的视觉模型进行识别。
        需要确保私有化部署的模型支持多模态输入（如 Qwen2.5-VL）。

        参数：
            prompt: 系统提示词（定义识别要求和输出格式）
            image_bytes: PNG 格式的页面图片二进制数据
            detail: 图片清晰度 — "high" 高清模式（默认），"low" 低分辨率模式

        返回：
            模型的完整文本响应

        异常：
            Exception: 所有重试均失败后抛出最后一次的异常
        """
        # 将图片编码为 base64 data URI 格式
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        image_url = f"data:{mime_type};base64,{image_b64}"

        messages = [
            {"role": "system", "content": "你是一个专业的银行流水识别助手。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url,
                            "detail": detail,
                        },
                    },
                ],
            },
        ]

        logger.info("[provider:private] vision 调用提示词 | prompt_len=%d\n--- prompt ---\n%s\n---", len(prompt), prompt)

        last_exception = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    "私有化视觉模型调用开始 — 模型: %s, 第 %d/%d 次尝试, 图片大小: %.1fKB",
                    self.vl_model, attempt, MAX_RETRIES, len(image_bytes) / 1024,
                )
                start_time = time.time()

                response = await self.client.chat.completions.create(
                    model=self.vl_model,
                    messages=messages,
                    temperature=0.1,
                    timeout=settings.parse_timeout,
                )

                elapsed = time.time() - start_time
                result = response.choices[0].message.content

                usage = response.usage
                logger.info(
                    "私有化视觉模型调用成功 — 耗时: %.2f秒, "
                    "输入token: %s, 输出token: %s, 总token: %s",
                    elapsed,
                    usage.prompt_tokens if usage else "N/A",
                    usage.completion_tokens if usage else "N/A",
                    usage.total_tokens if usage else "N/A",
                )
                return result

            except Exception as e:
                last_exception = e
                logger.warning(
                    "私有化视觉模型调用失败 — 第 %d/%d 次, 错误: %s",
                    attempt, MAX_RETRIES, str(e),
                )
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    logger.info("等待 %.1f 秒后重试...", delay)
                    import asyncio
                    await asyncio.sleep(delay)

        logger.error("私有化视觉模型调用最终失败，已重试 %d 次", MAX_RETRIES)
        raise last_exception

    async def vision_multi(
        self, prompt: str, image_bytes_list: list[bytes], detail: str = "high"
    ) -> str:
        """
        调用私有化多模态视觉模型（多图一次性传入）

        将多张图片放入同一请求的 content 数组。
        """
        content: list = [{"type": "text", "text": prompt}]
        for img_bytes in image_bytes_list:
            image_b64 = base64.b64encode(img_bytes).decode("utf-8")
            image_url = f"data:image/png;base64,{image_b64}"
            content.append({
                "type": "image_url",
                "image_url": {"url": image_url, "detail": detail},
            })

        messages = [
            {"role": "system", "content": "你是一个专业的银行流水识别助手。"},
            {"role": "user", "content": content},
        ]

        logger.info("[provider:private] vision_multi 调用提示词 | prompt_len=%d\n--- prompt ---\n%s\n---", len(prompt), prompt)

        total_size = sum(len(b) for b in image_bytes_list)
        last_exception = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    "私有化多图模型调用开始 — 模型: %s, 第 %d/%d 次尝试, 图片数: %d, 总大小: %.1fKB",
                    self.vl_model, attempt, MAX_RETRIES, len(image_bytes_list), total_size / 1024,
                )
                start_time = time.time()

                response = await self.client.chat.completions.create(
                    model=self.vl_model,
                    messages=messages,
                    temperature=0.1,
                    timeout=settings.parse_timeout,
                )

                elapsed = time.time() - start_time
                result = response.choices[0].message.content

                logger.info(
                    "私有化多图模型调用成功 — 耗时: %.2f秒, 图片数: %d",
                    elapsed, len(image_bytes_list),
                )
                return result

            except Exception as e:
                last_exception = e
                logger.warning(
                    "私有化多图模型调用失败 — 第 %d/%d 次, 错误: %s",
                    attempt, MAX_RETRIES, str(e),
                )
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    import asyncio
                    await asyncio.sleep(delay)

        logger.error("私有化多图模型调用最终失败，已重试 %d 次", MAX_RETRIES)
        raise last_exception

    async def stream_chat(self, prompt: str, text: str) -> AsyncGenerator[str, None]:
        """
        流式调用私有化文本模型

        使用 stream=True 参数实现流式输出，适用于报告生成场景。
        注意：部分私有化推理框架可能不完全支持流式输出，
        此时会在日志中记录警告并尝试正常返回。

        参数：
            prompt: 系统提示词（定义报告格式和要求）
            text: 待分析的数据内容

        生成：
            逐步产出模型响应的文本片段
        """
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ]

        logger.info("[provider:private] stream_chat 调用提示词 | prompt_len=%d | text_len=%d\n--- prompt ---\n%s\n--- user text (前500字) ---\n%s\n---", len(prompt), len(text), prompt, text[:500] + ("..." if len(text) > 500 else ""))
        logger.info(
            "私有化文本模型流式调用开始 — 模型: %s, 文本长度: %d",
            self.text_model, len(text),
        )
        start_time = time.time()
        total_chunks = 0

        try:
            stream = await self.client.chat.completions.create(
                model=self.text_model,
                messages=messages,
                temperature=0.3,
                stream=True,
                max_tokens=settings.max_output_tokens,
                timeout=settings.parse_timeout,
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    total_chunks += 1
                    yield content

            elapsed = time.time() - start_time
            logger.info(
                "私有化文本模型流式调用完成 — 耗时: %.2f秒, 共 %d 个chunk",
                elapsed, total_chunks,
            )

        except Exception as e:
            logger.error("私有化文本模型流式调用异常: %s", str(e))
            raise
