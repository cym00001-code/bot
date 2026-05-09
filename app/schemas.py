from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


MemoryType = Literal[
    "profile",
    "preference",
    "relationship",
    "event",
    "finance",
    "project",
    "instruction",
]


@dataclass(frozen=True)
class IncomingMessage:
    sender_id: str
    receiver_id: str
    content: str
    message_type: str = "text"
    message_id: str | None = None
    raw_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class MemoryCandidate:
    memory_type: MemoryType
    content: str
    confidence: float
    source: str = "chat"


@dataclass(frozen=True)
class RetrievedMemory:
    id: UUID
    memory_type: str
    content: str
    confidence: float


@dataclass(frozen=True)
class ExpenseRecordIntent:
    amount: Decimal
    category: str
    occurred_on: date
    note: str
    currency: str = "CNY"
    merchant: str | None = None


@dataclass(frozen=True)
class ExpenseQueryIntent:
    start_on: date
    end_on: date
    category: str | None = None
    kind: str = "expense"


class ToolExecutionResult(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_confirmation: bool = False
    result_summary: str
    data: dict[str, Any] = Field(default_factory=dict)


class ChatContext(BaseModel):
    user_id: UUID
    user_text: str
    memories: list[str] = Field(default_factory=list)
    recent_messages: list[dict[str, str]] = Field(default_factory=list)
    now: datetime
