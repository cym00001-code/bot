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
        self.executed = []

    def add(self, item) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flushed = True

    async def execute(self, statement) -> None:
        self.executed.append(statement)


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

    async def fake_create_or_replace(*args, **kwargs):
        return None

    registry.pending_actions.create_or_replace = fake_create_or_replace  # type: ignore[method-assign]

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


@pytest.mark.asyncio
async def test_confirmed_pending_action_executes_handler() -> None:
    session = FakeSession()
    registry = ToolRegistry(session)  # type: ignore[arg-type]
    user_id = uuid4()
    called_args = None

    class FakeAction:
        tool_name = "danger"
        arguments = {"target": "x"}

    async def fake_latest_pending(request_user_id):
        assert request_user_id == user_id
        return FakeAction()

    async def fake_mark_done(action):
        assert action.tool_name == "danger"

    registry.pending_actions.latest_pending = fake_latest_pending  # type: ignore[method-assign]
    registry.pending_actions.mark_done = fake_mark_done  # type: ignore[method-assign]

    async def handler(request_user_id, args):
        nonlocal called_args
        called_args = args
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

    result = await registry.execute_confirmed_pending(user_id)

    assert result is not None
    assert result.result_summary == "done"
    assert called_args == {"target": "x", "confirmed": True}
