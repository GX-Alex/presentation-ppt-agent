"""
数据库初始化与会话管理。
一阶段使用 SQLite，Schema 兼容后续迁移 PostgreSQL。
"""
import os
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/generalagent.db")

engine = create_async_engine(DATABASE_URL, echo=False)
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
