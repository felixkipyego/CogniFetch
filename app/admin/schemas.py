from datetime import datetime
from pydantic import BaseModel


class UserAdminOut(BaseModel):
    id: str
    email: str
    is_admin: bool
    created_at: datetime
    document_count: int

    class Config:
        from_attributes = True


class UserAdminUpdate(BaseModel):
    is_admin: bool


class ConfigOut(BaseModel):
    key: str
    value: str          # api_key is always returned masked
    source: str         # "database" | "environment"
    updated_at: datetime | None = None


class ConfigPatch(BaseModel):
    changes: dict[str, str]   # key → new value; blank value = delete DB override
