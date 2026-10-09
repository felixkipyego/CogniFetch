import enum
import uuid

from sqlalchemy import Boolean, Column, Enum, Float, ForeignKey, Integer, String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_admin = Column(Boolean, nullable=False, default=False, server_default="false")
    is_verified = Column(Boolean, nullable=False, default=True, server_default="true")
    email_token = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SystemConfig(Base):
    """Key-value store for runtime-editable settings that override env vars."""
    __tablename__ = "system_config"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DocumentStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(512), nullable=False)
    storage_path = Column(String(1024), nullable=False)
    mime_type = Column(String(128), nullable=False)
    status = Column(Enum(DocumentStatus), nullable=False, default=DocumentStatus.pending)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(512), nullable=False, default="New Chat")
    document_scope = Column(JSONB, nullable=True)  # list of document UUID strings, or null = all docs
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False)        # "user" | "assistant"
    content = Column(Text, nullable=False)
    cited_chunk_ids = Column(JSONB, nullable=True)   # list of chunk ID strings
    handled_by = Column(String(64), nullable=True)   # which sub-agent produced this message
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgentRunMetric(Base):
    """
    One row per completed agent turn — real chat traffic and eval harness
    runs alike (eval runs use a fixed eval user, so they show up as their own
    slice of the admin aggregates rather than being special-cased out).

    Deliberately not foreign-keyed to chat_sessions/chat_messages: keeping
    this table write-only and decoupled means the eval harness (which has no
    real ChatSession/ChatMessage rows) can write here with zero extra setup,
    and deleting a session/message never needs to cascade here.
    """
    __tablename__ = "agent_run_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    session_id = Column(UUID(as_uuid=True), nullable=True)
    message_id = Column(UUID(as_uuid=True), nullable=True)
    handled_by = Column(String(64), nullable=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    # Null when the configured model isn't in app/metrics/pricing.py's table —
    # an unpriced model should show up as "unknown" in aggregates, never as 0.
    cost_usd = Column(Float, nullable=True)
    node_latencies_ms = Column(JSONB, nullable=True)  # {node_name: total_ms}
    total_latency_ms = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
