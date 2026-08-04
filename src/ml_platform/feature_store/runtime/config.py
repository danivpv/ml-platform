from pydantic_settings import BaseSettings, SettingsConfigDict


class FeastRepoConfig(BaseSettings):
    """
    Configuration for Feast feature repository imports.
    Provides fallback defaults so that importing feature definitions during local
    testing or CI linting does not raise validation errors when AWS container
    environment variables are absent.
    """

    model_config = SettingsConfigDict(
        env_ignore_empty=False,
        case_sensitive=False,
    )

    feature_bucket: str = "FEATURE_BUCKET_NOT_SET"
