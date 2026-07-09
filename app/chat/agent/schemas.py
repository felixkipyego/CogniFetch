from typing import Literal
from pydantic import BaseModel
from langgraph.graph import MessagesState


class GradeDocuments(BaseModel):
    binary_score: Literal["yes", "no"]


class AgentState(MessagesState):
    rewrite_count: int
