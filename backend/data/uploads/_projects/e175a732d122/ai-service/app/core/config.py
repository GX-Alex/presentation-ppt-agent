"""
应用配置管理模块

使用 pydantic-settings 实现类型安全的配置管理，支持：
1. 从环境变量读取配置（优先级最高）
2. 从 .env 文件读取配置（开发环境便捷方式）
3. 代码中定义的默认值（兜底配置）

配置项命名规范：环境变量自动映射为大写下划线格式
例如 bailian_api_key -> BAILIAN_API_KEY
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    AI 服务全局配置类

    所有配置项均可通过环境变量或 .env 文件覆盖，
    字段名即为环境变量名（不区分大小写）。
    """

    # ==================== AI 服务提供商配置 ====================
    # 选择 AI 模型的调用方式：
    # - "bailian": 使用阿里云百炼平台（推荐生产环境使用）
    # - "private": 使用私有化部署的模型（vLLM/Ollama 等）
    ai_provider: str = "bailian"

    # ==================== 百炼平台配置 ====================
    # 阿里云百炼平台的 API Key，在百炼控制台创建获取
    # 注意：生产环境请通过环境变量注入，不要硬编码在代码或配置文件中
    bailian_api_key: str = ""

    # 百炼平台 API 端点地址
    # 百炼兼容 OpenAI 接口格式，使用 DashScope 兼容模式端点
    bailian_endpoint: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # 百炼模型名称（如 qwen3.5-35b-a3b，原生多模态）
    # 用于 PDF 图片识别、报告生成等，支持文本和图像输入
    bailian_model: str = "qwen3.5-35b-a3b"

    # ==================== 私有化模型配置 ====================
    # 私有化模型 API 端点地址
    # 支持 vLLM、Ollama 等兼容 OpenAI 接口的推理框架
    private_endpoint: str = "http://localhost:8001/v1"

    # 私有化视觉模型名称（需部署支持多模态输入的模型）
    private_vl_model: str = "Qwen2.5-VL-7B-Instruct"

    # 私有化文本模型名称
    private_text_model: str = "Qwen2.5-7B-Instruct"

    # ==================== 文件存储配置 ====================
    # 上传文件的本地存储目录
    # 由 Java 后端服务上传 PDF 文件后，将文件路径传递给 AI 服务
    upload_dir: str = "./uploads"

    # ==================== 解析配置 ====================
    # VL（视觉语言）模型单次请求最多处理的页数
    # 超过此页数将分批处理，避免单次请求过大导致超时或OOM
    max_pages_per_request: int = 5

    # 多文件解析时，单次请求最多传入的图片数
    # 超出则拆批调用，避免上下文过长导致超时或质量下降
    max_images_per_request: int = 10

    # 图片解析时，超过此大小（字节）的图片会先压缩再发送，避免 base64 超 API 20M 限制
    # 设为 0 表示不压缩
    image_compress_threshold: int = 5 * 1024 * 1024  # 5MB

    # 单页 PDF/图片解析的超时时间（秒）
    # 视觉模型解析大图可能较慢，图片解析易超时，建议 300 秒以上
    parse_timeout: int = 300

    # 智能问答/报告生成时的最大输出 token 数
    # 百炼/DashScope API 限制为 [1, 65536]，设为 65536（64k）以尽量完整输出
    max_output_tokens: int = 65536

    class Config:
        """
        pydantic-settings 配置类

        env_file: 指定 .env 文件路径，开发环境下可在此文件中配置所有参数
        env_file_encoding: .env 文件编码格式
        case_sensitive: 环境变量名不区分大小写
        """
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# 全局配置单例
# 在模块加载时即创建，后续所有模块通过 from app.core.config import settings 引用
settings = Settings()
