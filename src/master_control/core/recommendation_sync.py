from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RecommendationSyncResult:
    active: list[dict[str, object]] = field(default_factory=list)
    new: list[dict[str, object]] = field(default_factory=list)
    reopened: list[dict[str, object]] = field(default_factory=list)
    auto_resolved: list[dict[str, object]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "active": self.active,
            "new": self.new,
            "reopened": self.reopened,
            "auto_resolved": self.auto_resolved,
        }
