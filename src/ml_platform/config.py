"""
ml_platform/config.py
=================
Base configuration shared across microservices.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    """
    Base configuration class utilizing pydantic-settings.
    Validates environment variables at container startup.
    """

    app_name: str = "ml-platform"
    stage: str = "sandbox"
    service_prefix: str = "UNK"
    cdk_default_account: str | None = None
    aws_account_id: str | None = None
    cdk_default_region: str | None = None
    aws_region: str | None = None

    model_config = SettingsConfigDict(
        env_ignore_empty=False,
        case_sensitive=False,
    )

    @property
    def account(self) -> str:
        return self.cdk_default_account or self.aws_account_id or "975050146846"

    @property
    def region(self) -> str:
        return self.cdk_default_region or self.aws_region or "us-east-1"

    @property
    def ssm_mlflow_tracking_uri(self) -> str:
        return f"/{self.app_name}/{self.stage}/mlflow-tracking-uri"


settings = BaseConfig()
