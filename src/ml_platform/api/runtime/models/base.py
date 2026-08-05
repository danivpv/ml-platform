"""
api/runtime/models/base.py
==========================
Base classes for SQLModel ORM objects.
"""

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import event
from sqlmodel import Field as SQLField, SQLModel


class BaseMetadataModel(SQLModel):
    """Abstract base model providing UUID PK and audit fields."""

    id: uuid.UUID = SQLField(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = SQLField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = SQLField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
    created_by: int | None = SQLField(default=None)
    updated_by: int | None = SQLField(default=None)
    is_active: bool = SQLField(default=True)


@event.listens_for(BaseMetadataModel, "before_update", propagate=True)
def _receive_before_update(mapper, connection, target):
    """Automatically update the updated_at timestamp on save."""
    target.updated_at = datetime.now(timezone.utc)
