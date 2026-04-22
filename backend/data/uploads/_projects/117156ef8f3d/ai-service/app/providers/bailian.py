"""
阿里云百炼平台 AI 模型适配器

通过 OpenAI 兼容接口调用阿里云百炼（DashScope）的大模型服务。
百炼平台完全兼容 OpenAI SDK 的接口格式，因此可以直接使用 openai 库进行调用。

主要功能：
1. chat(): 调用文本模型（如 qwen-max）进行文本结构化
2. vision(): 调用视觉模型（如 qwen-vl-max）进行图片识别
3. stream_chat(): 流式调用文本模型，用于报告生成的实时输出

重试策略：所有模型调用均支持最多 3 次重试，应对网络抖动和服务端限流
"""

import base64
import logging
import time
from typing import AsyncGenerator

from openai import AsyncOpenAI

from app.core.config import settings
from app.providers.base import AIProvider

# 模块级日志器，日志中会显示 "app.providers.bailian" 便于定位
logger = logging.getLogger(__name__)

# 最大重试次数：调用失败后最多重试 3 次
MAX_RETRIES = 3
# 重试间隔基数（秒）：使用指数退避策略，实际等待时间 = base * 2^(retry_count)
RETRY_DELAY_BASE = 1.0


class BailianProvider(AIProvider):
    """
    阿里云百炼平台 AI 模型适配器

    通过百炼平台的 DashScope 兼容模式端点调用大模型。
    百炼平台支持 OpenAI 兼容的 API 格式，因此使用 openai SDK 即可调用。
    """

    def __init__(self):
        """
        初始化百炼适配器

        创建 AsyncOpenAI 客户端实例，配置百炼平台的端点和认证信息。
        使用异步客户端（AsyncOpenAI）以支持 FastAPI 的异步处理模型。
        """
        self.client = AsyncOpenAI(
            api_key=settings.bailian_api_key,
            base_url=settings.bailian_endpoint,
        )
        # 统一使用 Qwen3.5-Plus 多模态模型
        self.model = settings.bailian_model
        logger.info("[provider:bailian] 初始化完成 | model=%s", self.model)

    async def chat(self, prompt: str, text: str) -> str:
        """
        调用百炼文本模型

        使用 OpenAI 兼容接口调用百炼的文本模型（如 qwen-max），
        适用于文本型 PDF 的结构化解析和报告生成。

        参数：
            prompt: 系统提示词（定义角色和输出格式）
            text: 待处理的文本内容

        返回：
            模型的完整文本响应

        异常：
            Exception: 所有重试均失败后抛出最后一次的异常
        """
        # 构造消息列表：system 消息设定模型行为，user 消息传入待处理文本
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ]

        logger.info("[provider:bailian] chat 调用提示词 | prompt_len=%d | text_len=%d\n--- prompt ---\n%s\n--- user text (前500字) ---\n%s\n---", len(prompt), len(text), prompt, text[:500] + ("..." if len(text) > 500 else ""))

        last_exception = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    "[provider:bailian] chat 调用 | model=%s | attempt=%d/%d | text_len=%d",
                    self.model, attempt, MAX_RETRIES, len(text),
                )
                start_time = time.time()

                # 调用百炼兼容的 OpenAI Chat Completions 接口
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1,  # 低温度值确保输出稳定，减少随机性
                    max_tokens=settings.max_output_tokens,
                    timeout=settings.parse_timeout,
                )

                elapsed = time.time() - start_time
                result = response.choices[0].message.content

                # 记录调用成功日志，包含耗时和 token 消耗信息
                usage = response.usage
                logger.info(
                    "[provider:bailian] chat 成功 | elapsed=%.2fs | tokens=%d+%d=%d",
                    elapsed,
                    usage.prompt_tokens if usage else 0,
                    usage.completion_tokens if usage else 0,
                    usage.total_tokens if usage else 0,
                )
                return result

            except Exception as e:
                last_exception = e
                logger.warning(
                    "[provider:bailian] chat 失败 | attempt=%d/%d | error=%s",
                    attempt, MAX_RETRIES, str(e),
                )
                if attempt < MAX_RETRIES:
                    # 指数退避等待：1秒、2秒、4秒...
                    delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    logger.info("等待 %.1f 秒后重试...", delay)
                    import asyncio
                    await asyncio.sleep(delay)

        # 所有重试均失败，抛出最后一次异常
        logger.error("[provider:bailian] chat 最终失败 | retries=%d", MAX_RETRIES)
        raise last_exception

    async def vision(
        self,
        prompt: str,
        image_bytes: bytes,
        detail: str = "high",
        mime_type: str = "image/png",
    ) -> str:
        """
        调用百炼多模态视觉模型

        将页面图片编码为 base64 后，通过 OpenAI 兼容接口调用百炼的视觉模型。
        视觉模型可以"看懂"图片中的表格和文字，适用于扫描型 PDF 的识别。

        参数：
            prompt: 系统提示词（定义识别要求和输出格式）
            image_bytes: PNG 格式的页面图片二进制数据
            detail: 图片清晰度 — "high" 高清模式（默认），"low" 低分辨率模式

        返回：
            模型的完整文本响应（通常是 JSON 格式的识别结果）

        异常：
            Exception: 所有重试均失败后抛出最后一次的异常
        """
        # 将图片二进制数据编码为 base64 字符串
        # OpenAI 兼容接口要求图片以 data URI 格式传入
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        image_url = f"data:{mime_type};base64,{image_b64}"

        # 构造多模态消息：包含文本提示和图片内容
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
                            "detail": detail,  # 图片分辨率级别
                        },
                    },
                ],
            },
        ]

        logger.info("[provider:bailian] vision 调用提示词 | prompt_len=%d\n--- prompt ---\n%s\n---", len(prompt), prompt)

        last_exception = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    "百炼模型调用开始 — 模型: %s, 第 %d/%d 次尝试, 图片大小: %.1fKB",
                    self.model, attempt, MAX_RETRIES, len(image_bytes) / 1024,
                )
                start_time = time.time()

                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1,
                    timeout=settings.parse_timeout,
                )

                elapsed = time.time() - start_time
                result = response.choices[0].message.content

                usage = response.usage
                logger.info(
                    "百炼视觉模型调用成功 — 耗时: %.2f秒, "
                    "输入token: %d, 输出token: %d, 总token: %d",
                    elapsed,
                    usage.prompt_tokens if usage else 0,
                    usage.completion_tokens if usage else 0,
                    usage.total_tokens if usage else 0,
                )
                return result

            except Exception as e:
                last_exception = e
                logger.warning(
                    "百炼视觉模型调用失败 — 第 %d/%d 次, 错误: %s",
                    attempt, MAX_RETRIES, str(e),
                )
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    logger.info("等待 %.1f 秒后重试...", delay)
                    import asyncio
                    await asyncio.sleep(delay)

        logger.error("百炼视觉模型调用最终失败，已重试 %d 次", MAX_RETRIES)
        raise last_exception

    async def vision_multi(
        self, prompt: str, image_bytes_list: list[bytes], detail: str = "high"
    ) -> str:
        """
        调用百炼多模态视觉模型（多图一次性传入）

        将多张图片放入同一请求的 content 数组，减少调用次数。
        OpenAI 兼容接口支持多 image_url。
        """
        # 构建 content：文本 + 多张图片
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

        logger.info("[provider:bailian] vision_multi 调用提示词 | prompt_len=%d\n--- prompt ---\n%s\n---", len(prompt), prompt)

        total_size = sum(len(b) for b in image_bytes_list)
        last_exception = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    "百炼多图模型调用开始 — 模型: %s, 第 %d/%d 次尝试, 图片数: %d, 总大小: %.1fKB",
                    self.model, attempt, MAX_RETRIES, len(image_bytes_list), total_size / 1024,
                )
                start_time = time.time()

                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1,
                    timeout=settings.parse_timeout,
                )

                elapsed = time.time() - start_time
                result = response.choices[0].message.content

                usage = response.usage
                logger.info(
                    "百炼多图模型调用成功 — 耗时: %.2f秒, 图片数: %d",
                    elapsed, len(image_bytes_list),
                )
                return result

            except Exception as e:
                last_exception = e
                logger.warning(
                    "百炼多图模型调用失败 — 第 %d/%d 次, 错误: %s",
                    attempt, MAX_RETRIES, str(e),
                )
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    import asyncio
                    await asyncio.sleep(delay)

        logger.error("百炼多图模型调用最终失败，已重试 %d 次", MAX_RETRIES)
        raise last_exception

    async def stream_chat(self, prompt: str, text: str) -> AsyncGenerator[str, None]:
        """
        流式调用百炼文本模型

        使用 stream=True 参数实现流式输出，模型生成的内容会逐步返回，
        前端可以通过 SSE（Server-Sent Events）实时展示生成进度。

        参数：
            prompt: 系统提示词（定义报告格式和要求）
            text: 待分析的数据内容

        生成：
            逐步产出模型响应的文本片段（每个 chunk 通常是几个字到一句话）
        """
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ]

        logger.info("[provider:bailian] stream_chat 调用提示词 | prompt_len=%d | text_len=%d\n--- prompt ---\n%s\n--- user text (前500字) ---\n%s\n---", len(prompt), len(text), prompt, text[:500] + ("..." if len(text) > 500 else ""))
        logger.info(
            "百炼模型流式调用开始 — 模型: %s, 文本长度: %d",
            self.model, len(text),
        )
        start_time = time.time()
        total_chunks = 0

        try:
            # stream=True 启用流式输出，返回一个异步迭代器
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,  # 报告生成场景允许略高的创造性
                stream=True,
                max_tokens=settings.max_output_tokens,
                timeout=settings.parse_timeout,
            )

            # 逐个读取流式响应的 chunk
            async for chunk in stream:
                # 每个 chunk 的 choices[0].delta.content 包含一小段文本
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    total_chunks += 1
                    yield content

            elapsed = time.time() - start_time
            logger.info(
                "百炼文本模型流式调用完成 — 耗时: %.2f秒, 共 %d 个chunk",
                elapsed, total_chunks,
            )

        except Exception as e:
            logger.error("百炼文本模型流式调用异常: %s", str(e))
            raise
