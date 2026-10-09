from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass(frozen=True)
class ChatMessage:
    """One persisted user or assistant message."""

    id: str
    session_id: str
    user_id: str
    role: str
    content: str
    created_at: datetime
    citations: List[str] = field(default_factory=list)
    source_types: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChatTurn:
    """A logical user question and its assistant response."""

    user_message: str
    assistant_message: Optional[str] = None
    citations: List[str] = field(default_factory=list)
    source_types: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
