from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    READ_ONLY = "read_only"
    MUTATING_SAFE = "mutating_safe"
    PRIVILEGED = "privileged"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    risk: RiskLevel
    arguments: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "risk": self.risk.value,
            "arguments": list(self.arguments),
        }


class Tool(ABC):
    spec: ToolSpec

    @abstractmethod
    def invoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class ToolError(RuntimeError):
    """Base class for tool execution errors."""


class ToolArgumentError(ToolError):
    """Raised when a tool receives invalid arguments."""


def get_string_argument(
    arguments: Mapping[str, Any],
    name: str,
    *,
    required: bool = False,
    default: str | None = None,
) -> str | None:
    value = arguments.get(name, default)
    if value is None:
        if required:
            raise ToolArgumentError(f"Missing required argument: {name}")
        return None
    if not isinstance(value, str):
        raise ToolArgumentError(f"Argument '{name}' must be a string.")

    normalized = value.strip()
    if required and not normalized:
        raise ToolArgumentError(f"Argument '{name}' cannot be empty.")
    return normalized or default


def get_int_argument(
    arguments: Mapping[str, Any],
    name: str,
    *,
    required: bool = False,
    default: int | None = None,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int | None:
    value = arguments.get(name, default)
    if value is None:
        if required:
            raise ToolArgumentError(f"Missing required argument: {name}")
        return None

    if isinstance(value, bool):
        raise ToolArgumentError(f"Argument '{name}' must be an integer.")

    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError as exc:
            raise ToolArgumentError(f"Argument '{name}' must be an integer.") from exc
    else:
        raise ToolArgumentError(f"Argument '{name}' must be an integer.")

    if min_value is not None and parsed < min_value:
        raise ToolArgumentError(f"Argument '{name}' must be >= {min_value}.")
    if max_value is not None and parsed > max_value:
        raise ToolArgumentError(f"Argument '{name}' must be <= {max_value}.")
    return parsed
