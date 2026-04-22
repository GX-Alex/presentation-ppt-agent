"""
项目配置 — 环境变量 & 常量
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── LLM 配置（阿里云百炼 Qwen3-VL-Flash，OpenAI 兼容方式） ──
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen3.5-35b-a3b")
LLM_EXTRACT_MODEL: str = os.getenv("LLM_EXTRACT_MODEL", "qwen3.5-35b-a3b")  # 流水提取模型
LLM_META_MODEL: str = os.getenv("LLM_META_MODEL", "qwen3.5-35b-a3b")  # 元数据提取模型
# Qwen3 思考模式开关：False = 非思考模式（速度快、输出稳定，适合结构化提取）
LLM_ENABLE_THINKING: bool = os.getenv("LLM_ENABLE_THINKING", "false").lower() == "true"
# 非思考模式下 temperature 建议范围 [0.0, 1.0]；思考模式固定为 1.0
LLM_EXTRACT_TEMPERATURE: float = float(os.getenv("LLM_EXTRACT_TEMPERATURE", "0.1"))  # 流水提取：低随机性
LLM_META_TEMPERATURE: float = float(os.getenv("LLM_META_TEMPERATURE", "0.1"))      # 元数据提取：低随机性
LLM_EXTRACT_MAX_TOKENS: int = int(os.getenv("LLM_EXTRACT_MAX_TOKENS", "8000"))      # 流水提取最大输出token

# ── 请求 & 重试 ──
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "1200"))
RETRY_COUNT: int = int(os.getenv("RETRY_COUNT", "2"))
RETRY_DELAY: int = int(os.getenv("RETRY_DELAY", "3"))

# ── 并发 ──
MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "4"))
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "8"))  # PDF 分块大小：每组最多发送给 LLM 的图片数
MAX_CHUNK_WORKERS: int = int(os.getenv("MAX_CHUNK_WORKERS", "6"))  # 同时发往 LLM 的 chunk 并发上限

# ── PDF 转图片 ──
PDF_ZOOM: float = float(os.getenv("PDF_ZOOM", "2.8"))
IMAGE_FORMAT: str = os.getenv("IMAGE_FORMAT", "PNG").upper()  # "PNG" 或 "JPEG"
PDF_QUALITY: int = int(os.getenv("PDF_QUALITY", "85"))  # JPEG 质量（仅 IMAGE_FORMAT="JPEG" 时用）
PDF_MAX_WIDTH: int = int(os.getenv("PDF_MAX_WIDTH", "2000"))

# ── 日志 ──
LOG_DIR: str = os.getenv("LOG_DIR", "logs")
LOG_RETENTION_DAYS: int = int(os.getenv("LOG_RETENTION_DAYS", "90"))  # 3个月

# ── 输出 ──
OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "output")

# ── 余额连续性校验 ──
# 余额差容忍值（元），超过此值且翻转借贷方向后吻合则自动修正
BALANCE_CORRECTION_TOLERANCE: float = float(os.getenv("BALANCE_CORRECTION_TOLERANCE", "0.01"))

# ── 回调 ──
# 上游接收处理结果的固定回调地址（POST），留空则不回调（仅同步响应）
CALLBACK_URL: str = os.getenv("CALLBACK_URL", "")

# ── Dify 提示词动态拉取 ──
# 自部署 Dify 地址，留空则不从 Dify 拉取（使用代码内置提示词）
DIFY_BASE_URL: str = os.getenv("DIFY_BASE_URL", "")
# 两个文本生成 App 的 API Key（在 Dify「访问 API」页面获取）
DIFY_EXTRACT_TRANSACTIONS_API_KEY: str = os.getenv("DIFY_EXTRACT_TRANSACTIONS_API_KEY", "")
DIFY_EXTRACT_METADATA_API_KEY: str = os.getenv("DIFY_EXTRACT_METADATA_API_KEY", "")
# 提示词缓存时间（秒），默认 10 分钟；修改 Dify 提示词后最多等待此时间生效
PROMPT_CACHE_TTL: int = int(os.getenv("PROMPT_CACHE_TTL", "600"))

# ── 服务 ──
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))
