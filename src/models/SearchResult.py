from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class SearchResult:
    text: str
    source: str
    page: int | None = None
    score: float | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)
