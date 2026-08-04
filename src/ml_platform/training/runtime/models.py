from datetime import datetime

from pydantic import BaseModel, Field


class EntityRow(BaseModel):
    """
    One entity row used to build the entity_df for Feast feature retrieval.
    """

    entity_id: str = Field(..., description="Unique customer/entity identifier")
    event_timestamp: datetime = Field(
        ..., description="Point-in-time timestamp for Feast historical feature join"
    )
