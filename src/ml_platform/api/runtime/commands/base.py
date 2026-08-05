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


class BaseCommand(ABC):
    """Base class for commands that do not require database transactions."""

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return await self._execute(*args, **kwargs)
        except CatalogException:
            # Let our specific domain exceptions pass through
            raise
        except Exception as e:
            logger.exception("Unexpected error in command execution")
            raise UpstreamServiceError(message=f"An upstream service failed: {str(e)}")

    @abstractmethod
    async def _execute(self, *args: Any, **kwargs: Any) -> Any:
        pass


class BaseDBCommand(BaseCommand):
    """Base class for commands that execute within a database session transaction."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        try:
            result = await self._execute(*args, **kwargs)
            await self.session.commit()
            return result
        except CatalogException:
            # Domain exceptions might imply a deliberate rollback
            await self.session.rollback()
            raise
        except SQLAlchemyError as e:
            # Any database-related error
            await self.session.rollback()
            logger.exception("Database error during command execution")
            raise DatabaseError(message=f"A database error occurred: {str(e)}")
        except Exception as e:
            # Catch-all for unexpected Python errors or other libraries
            await self.session.rollback()
            logger.exception("Unexpected error in DB command execution")
            raise UpstreamServiceError(message=f"An upstream service failed: {str(e)}")

    @abstractmethod
    async def _execute(self, *args: Any, **kwargs: Any) -> Any:
        pass
