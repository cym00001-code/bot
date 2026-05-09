from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.schemas import ToolExecutionResult

RiskLevel = Literal["low", "medium", "high"]
ToolHandler = Callable[[UUID, dict[str, Any]], Awaitable[ToolExecutionResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    risk_level: RiskLevel
    requires_confirmation: bool
    handler: ToolHandler

    def as_deepseek_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
