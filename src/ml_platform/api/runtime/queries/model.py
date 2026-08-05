from sqlalchemy.ext.asyncio import AsyncSession

from ml_platform.api.runtime.exceptions import ModelNotFoundError
from ml_platform.api.runtime.models.model import Model
from ml_platform.api.runtime.queries.base import BaseDBQuery
from ml_platform.api.runtime.repositories.model import ModelRepository


class GetModelQuery(BaseDBQuery):
    def __init__(self, session: AsyncSession):
        super().__init__(session)
        self.repo = ModelRepository(session)

    async def _execute(self, model_name: str) -> Model:
        model = await self.repo.get_by_name(model_name)
        if not model:
            raise ModelNotFoundError(model_name=model_name)
        return model


class ListModelsQuery(BaseDBQuery):
    def __init__(self, session: AsyncSession):
        super().__init__(session)
        self.repo = ModelRepository(session)

    async def _execute(self) -> list[Model]:
        return await self.repo.get_all()
