"""create catalog schema and models

Revision ID: df196303ff88
Revises: b7e4c1a90f23
Create Date: 2026-08-04 21:43:34.758498

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'df196303ff88'
down_revision: Union[str, Sequence[str], None] = 'b7e4c1a90f23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


import sqlmodel

def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS catalog")
    
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('models', schema='catalog'):
        op.create_table('models',
            sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.Column('updated_by', sa.Integer(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('model_name', sqlmodel.AutoString(), nullable=False),
            sa.Column('feature_view', sqlmodel.AutoString(), nullable=False),
            sa.Column('feature_refs', sqlmodel.AutoString(), nullable=False),
            sa.Column('label_column', sqlmodel.AutoString(), nullable=False),
            sa.Column('mlflow_experiment', sqlmodel.AutoString(), nullable=False),
            sa.Column('owner', sqlmodel.AutoString(), nullable=False),
            sa.Column('cron_schedule', sqlmodel.AutoString(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('model_name'),
            schema='catalog'
        )

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('models', schema='catalog')
    op.execute("DROP SCHEMA IF EXISTS catalog")
