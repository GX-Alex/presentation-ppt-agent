"""
数据库初始化与会话管理。
一阶段使用 SQLite，Schema 兼容后续迁移 PostgreSQL。
"""
import os
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/generalagent.db")

engine = create_async_engine(DATABASE_URL, echo=False)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            row = cursor.fetchone()
            if row and row[0].lower() != "wal":
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "SQLite journal_mode WAL 设置失败，当前模式: %s，并发写入可能出现锁错误", row[0]
                )
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""
    pass


async def get_session() -> AsyncSession:
    """FastAPI 依赖: 提供数据库会话。"""
    async with async_session() as session:
        yield session


async def init_db():
    """启动时创建所有数据表。"""
    # 导入所有模型以注册到 Base.metadata
    from app.models import tables  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 对已存在的表补充新列（SQLite 不支持 IF NOT EXISTS，捕获异常即可）
        for sql in [
            "ALTER TABLE task_messages ADD COLUMN reasoning_content TEXT",
        ]:
            try:
                await conn.exec_driver_sql(sql)
            except Exception:
                pass  # 列已存在则忽略
