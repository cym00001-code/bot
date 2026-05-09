from __future__ import annotations

from uuid import uuid4

import pytest

from app.schemas import ToolExecutionResult
from app.tools.base import ToolSpec
from app.tools.registry import ToolRegistry


class FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.flushed = False

    def add(self, item) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flushed = True


@pytest.mark.asyncio
async def test_unknown_tool_returns_structured_result() -> None:
    session = FakeSession()
    registry = ToolRegistry(session)  # type: ignore[arg-type]

    result = await registry.execute("missing_tool", uuid4(), {"x": 1})

    assert result.tool_name == "missing_tool"
    assert result.data["ok"] is False
    assert session.added == []


@pytest.mark.asyncio
async def test_confirmation_required_blocks_high_risk_handler() -> None:
    session = FakeSession()
    registry = ToolRegistry(session)  # type: ignore[arg-type]
    called = False

    async def handler(user_id, args):
        nonlocal called
        called = True
        return ToolExecutionResult(tool_name="danger", result_summary="done")

    registry.register(
        ToolSpec(
            name="danger",
            description="danger",
            parameters={"type": "object", "properties": {}},
            risk_level="high",
            requires_confirmation=True,
            handler=handler,
        )
    )

    result = await registry.execute("danger", uuid4(), {})

    assert not called
    assert result.requires_confirmation is True
    assert session.flushed is True
