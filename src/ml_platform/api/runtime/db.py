"""
api/runtime/db.py
=================
Async SQLAlchemy engine and session factory for the Model Catalog.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ml_platform.api.runtime.config import config

engine = create_async_engine(
    config.database_url,
    echo=False,
    future=True,
    # Pool config for a lightweight API
    pool_size=5,
    max_overflow=10,
)

async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI routes to get an async DB session."""
    async with async_session_maker() as session:
        yield session
