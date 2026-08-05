"""use timezone aware datetimes

Revision ID: be2d7fa00da7
Revises: df196303ff88
Create Date: 2026-08-04 22:07:26.150264

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be2d7fa00da7'
down_revision: Union[str, Sequence[str], None] = 'df196303ff88'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE catalog.models ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE catalog.models ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE")

def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE catalog.models ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE")
    op.execute("ALTER TABLE catalog.models ALTER COLUMN updated_at TYPE TIMESTAMP WITHOUT TIME ZONE")
