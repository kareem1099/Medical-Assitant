from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class User:
    """Application user; password hashes are never exposed by this model."""

    id: str
    email: str
    display_name: str
    created_at: datetime
    last_login_at: Optional[datetime] = None
    is_active: bool = True
