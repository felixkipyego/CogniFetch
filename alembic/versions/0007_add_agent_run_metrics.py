"""add agent_run_metrics table

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_run_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("handled_by", sa.String(64), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("node_latencies_ms", postgresql.JSONB(), nullable=True),
        sa.Column("total_latency_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_run_metrics_user_id", "agent_run_metrics", ["user_id"])
    op.create_index("ix_agent_run_metrics_created_at", "agent_run_metrics", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_run_metrics_created_at", table_name="agent_run_metrics")
    op.drop_index("ix_agent_run_metrics_user_id", table_name="agent_run_metrics")
    op.drop_table("agent_run_metrics")
