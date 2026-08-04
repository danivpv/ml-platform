from datetime import datetime

from pydantic import BaseModel, Field


class PredictionRecord(BaseModel):
    """
    One validated prediction output row, written to S3 as NDJSON.
    """

    entity_id: str = Field(..., description="Entity this prediction belongs to")
    score: float = Field(..., description="Model output score (raw or probability)")
    model_uri: str = Field(
        ..., description="MLflow model URI used to produce this prediction"
    )
    predicted_at: datetime = Field(
        ..., description="UTC timestamp when the prediction was generated"
    )
