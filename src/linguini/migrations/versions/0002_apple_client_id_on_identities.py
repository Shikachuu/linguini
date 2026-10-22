"""apple client id on identities

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22 21:28:39.718700
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("identities", schema=None) as batch_op:
        batch_op.add_column(sa.Column("apple_client_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("identities", schema=None) as batch_op:
        batch_op.drop_column("apple_client_id")
