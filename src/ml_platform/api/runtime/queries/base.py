import logging
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ml_platform.api.runtime.exceptions import (
    CatalogException,
    DatabaseError,
    UpstreamServiceError,
)

logger = logging.getLogger(__name__)


class BaseQuery(ABC):
    """Base class for queries that do not require database transactions."""

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return await self._execute(*args, **kwargs)
        except CatalogException:
            raise
        except Exception as e:
            logger.exception("Unexpected error in query execution")
            raise UpstreamServiceError(message=f"An upstream service failed: {str(e)}")

    @abstractmethod
    async def _execute(self, *args: Any, **kwargs: Any) -> Any:
        pass


class BaseDBQuery(BaseQuery):
    """Base class for queries that read from a database session."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        try:
            # Queries don't mutate state, so no commit/rollback is needed
            # for successful reads, but rollback on failure is safe.
            return await self._execute(*args, **kwargs)
        except CatalogException:
            raise
        except SQLAlchemyError as e:
            logger.exception("Database error during query execution")
            raise DatabaseError(message=f"A database error occurred: {str(e)}")
        except Exception as e:
            logger.exception("Unexpected error in DB query execution")
            raise UpstreamServiceError(message=f"An upstream service failed: {str(e)}")

    @abstractmethod
    async def _execute(self, *args: Any, **kwargs: Any) -> Any:
        pass
