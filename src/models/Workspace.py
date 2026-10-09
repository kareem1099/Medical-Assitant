from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Workspace:
    """A user-owned document and retrieval boundary."""

    id: str
    user_id: str
    name: str
    description: str
    created_at: datetime
