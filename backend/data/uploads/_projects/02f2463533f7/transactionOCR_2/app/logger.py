"""
日志配置 — RotatingFileHandler，按大小轮转并自动压缩
"""
import os
import glob
import logging
import gzip
import shutil
from datetime import datetime
from logging.handlers import RotatingFileHandler
from app.config import LOG_DIR, LOG_RETENTION_DAYS

LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 日志配置
LOG_FILE_SIZE = 10 * 1024 * 1024  # 10MB：单个日志文件大小限制
LOG_BACKUP_COUNT = 10              # 保留 10 个备份文件（最多 100MB）


class CompressedRotatingFileHandler(RotatingFileHandler):
    """按大小轮转，压缩备份文件并以日期命名，便于追溯"""

    def doRollover(self):
        """
        完全接管轮转逻辑：
        1. 关闭当前流
        2. 将 app.log 压缩为 app.log.YYYY-MM-DD.gz（同天多次则加 _1/_2 后缀）
        3. 按 backupCount 清理最旧的 gz 文件
        4. 重新打开 app.log（清空，从头写入）
        """
        if self.stream:
            self.stream.close()
            self.stream = None

        # 生成带日期的压缩文件名，同天多次轮转自动加序号
        date_str = datetime.now().strftime("%Y-%m-%d")
        gz_file = f"{self.baseFilename}.{date_str}.gz"
        counter = 1
        while os.path.exists(gz_file):
            gz_file = f"{self.baseFilename}.{date_str}_{counter}.gz"
            counter += 1

        # 压缩当前日志
        if os.path.exists(self.baseFilename):
            try:
                with open(self.baseFilename, 'rb') as f_in:
                    with gzip.open(gz_file, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            except Exception as e:
                print(f"压缩日志失败 {self.baseFilename}: {e}")

        # 按修改时间保留最新的 backupCount 个 gz，删除多余的
        base_dir = os.path.dirname(self.baseFilename) or "."
        base_name = os.path.basename(self.baseFilename)
        gz_files = sorted(
            glob.glob(os.path.join(base_dir, f"{base_name}.*.gz")),
            key=os.path.getmtime,
            reverse=True,
        )
        for old_file in gz_files[self.backupCount:]:
            try:
                os.remove(old_file)
            except Exception:
                pass

        # 重新打开（清空内容，开始新一轮写入）
        if not self.delay:
            self.stream = self._open()


def setup_logger(name: str = "transaction_ocr") -> logging.Logger:
    """
    配置并返回项目根 Logger。
    - 文件按大小轮转（10MB），轮换时自动压缩
    - 保留最多 10 个备份文件
    - 同时输出到控制台
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # 避免重复添加

    logger.setLevel(logging.DEBUG)

    # ── 文件 Handler（按大小轮转，轮换时压缩） ──
    file_handler = CompressedRotatingFileHandler(
        filename=os.path.join(LOG_DIR, "app.log"),
        maxBytes=LOG_FILE_SIZE,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    # ── 控制台 Handler ──
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# 项目全局 Logger 实例
logger = setup_logger()
