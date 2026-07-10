import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class SessionCreate(BaseModel):
    title: str = "New Chat"
    document_scope: Optional[List[uuid.UUID]] = None


class SessionOut(BaseModel):
    id: uuid.UUID
    title: str
    document_scope: Optional[List[uuid.UUID]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    content: str


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    cited_chunk_ids: Optional[List] = None  # list of {document_id, pages} objects
    created_at: datetime

    model_config = {"from_attributes": True}
