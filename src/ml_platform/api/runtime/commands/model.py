import logging

from mlflow.exceptions import RestException
from mlflow.tracking import MlflowClient
from sqlalchemy.ext.asyncio import AsyncSession

from ml_platform.api.runtime.commands.base import BaseDBCommand
from ml_platform.api.runtime.config import config
from ml_platform.api.runtime.exceptions import (
    ModelConflictError,
    ModelNotFoundError,
    UpstreamServiceError,
)
from ml_platform.api.runtime.models.model import (
    Model,
    ModelCreateInput,
    ModelUpdateInput,
)
from ml_platform.api.runtime.repositories.model import ModelRepository
from ml_platform.api.runtime.services.scheduler import delete_schedule, upsert_schedule

logger = logging.getLogger(__name__)


class CreateModelCommand(BaseDBCommand):
    def __init__(self, session: AsyncSession):
        super().__init__(session)
        self.repo = ModelRepository(session)

    async def _execute(self, model_in: ModelCreateInput) -> Model:
        existing = await self.repo.get_by_name(model_in.model_name)
        if existing:
            raise ModelConflictError(model_name=model_in.model_name)
        return await self.repo.create(model_in)


class UpdateModelScheduleCommand(BaseDBCommand):
    def __init__(self, session: AsyncSession):
        super().__init__(session)
        self.repo = ModelRepository(session)

    async def _execute(self, model_name: str, schedule_in: ModelUpdateInput) -> Model:
        model = await self.repo.get_by_name(model_name)
        if not model:
            raise ModelNotFoundError(model_name=model_name)

        if schedule_in.cron_schedule:
            # 1. Validate the artifact exists in MLflow before scheduling
            client = MlflowClient(tracking_uri=config.mlflow_tracking_uri)
            try:
                client.get_model_version_by_alias(model_name, "champion")
            except RestException as e:
                if e.error_code == "RESOURCE_DOES_NOT_EXIST":
                    raise UpstreamServiceError(
                        message="Model artifact with @champion alias not found in MLflow. Cannot schedule inference.",
                        status_code=400,
                    )
                raise UpstreamServiceError(
                    message=f"Failed to communicate with MLflow: {str(e)}"
                )

            # 2. Apply schedule in AWS
            await upsert_schedule(model_name, schedule_in.cron_schedule, model.feature_refs)
        else:
            await delete_schedule(model_name)

        model.cron_schedule = schedule_in.cron_schedule
        return await self.repo.update(model)
