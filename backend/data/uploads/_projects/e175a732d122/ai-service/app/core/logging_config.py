"""
日志配置模块

为整个 AI 服务配置统一的日志格式和输出方式：
1. 控制台输出：开发调试用，便于实时查看系统运行情况
2. 文件输出：生产环境用，按大小滚动切割
3. 统一格式：时间 | 级别 | 模块 | 消息内容

日志规范：各模块应输出清晰的流程节点，便于排查问题：
- 接口入口：记录请求关键参数（如 file_path、subject_id）
- 关键步骤：记录耗时、结果数量（如解析完成、交易笔数）
- 异常情况：记录错误原因和上下文
"""

import logging
import sys
from logging.handlers import RotatingFileHandler


def setup_logging(level: str = "INFO") -> None:
    """
    初始化全局日志配置

    参数：
        level: 日志级别字符串，默认 INFO
               可通过环境变量 LOG_LEVEL 覆盖

    日志格式示例：
        2024-03-15 10:30:00 | INFO     | app.api.parse | [parse] 解析开始 file_path=/path/to.pdf
    """
    # 日志格式：时间 | 级别（左对齐8字符） | 模块名 | 消息内容
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

    # ---------- 控制台日志处理器 ----------
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    # ---------- 文件日志处理器 ----------
    file_handler = RotatingFileHandler(
        filename="ai-service.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # ---------- 配置根日志器 ----------
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # ---------- 降低第三方库的日志级别 ----------
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    logging.info("日志系统初始化完成 | level=%s", level)
