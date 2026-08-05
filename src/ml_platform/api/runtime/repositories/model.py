"""
api/runtime/repositories.py
===========================
Repository classes encapsulating database interactions.
"""

from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ml_platform.api.runtime.models.model import Model, ModelCreateInput


class ModelRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, model_in: ModelCreateInput) -> Model:
        model = Model(**model_in.model_dump())
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return model

    async def get_all(self) -> List[Model]:
        result = await self.session.execute(select(Model))
        return list(result.scalars().all())

    async def get_by_name(self, model_name: str) -> Optional[Model]:
        result = await self.session.execute(
            select(Model).where(Model.model_name == model_name)
        )
        return result.scalars().first()

    async def update(self, model: Model) -> Model:
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return model
