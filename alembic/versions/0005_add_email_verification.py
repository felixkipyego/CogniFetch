"""add email verification to users

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "users",
        sa.Column("email_token", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "email_token")
    op.drop_column("users", "is_verified")
