from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


def get_context_key(item: Dict[str, Any]) -> str:
    path = item.get("path", "")
    return f"{path}" if path else item.get("item_id", "")


@dataclass
class WorkQueue:
    items_by_role: Dict[str, List[str]] = field(default_factory=dict)

    def enqueue(self, item_id: str, role: str) -> None:
        if role not in self.items_by_role:
            self.items_by_role[role] = []
        if item_id not in self.items_by_role[role]:
            self.items_by_role[role].append(item_id)

    def dequeue(self, role: str) -> Optional[str]:
        if role in self.items_by_role and self.items_by_role[role]:
            return self.items_by_role[role].pop(0)
        return None
