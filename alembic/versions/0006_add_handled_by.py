"""add handled_by to chat_messages

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("handled_by", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "handled_by")
