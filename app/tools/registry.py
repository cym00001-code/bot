from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ToolCall
from app.schemas import ToolExecutionResult
from app.tools.base import ToolSpec


class ToolRegistry:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def list_for_model(self) -> list[dict[str, Any]]:
        return [tool.as_deepseek_tool() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)

    async def execute(
        self,
        name: str,
        user_id: UUID,
        arguments: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        arguments = arguments or {}
        spec = self._tools.get(name)
        if spec is None:
            return ToolExecutionResult(
                tool_name=name,
                arguments=arguments,
                risk_level="low",
                requires_confirmation=False,
                result_summary=f"未知工具：{name}",
                data={"ok": False},
            )

        if spec.requires_confirmation and not arguments.get("confirmed"):
            result = ToolExecutionResult(
                tool_name=name,
                arguments=arguments,
                risk_level=spec.risk_level,
                requires_confirmation=True,
                result_summary="这个操作需要你明确确认后才会执行。",
                data={"ok": False, "confirmation_required": True},
            )
        else:
            result = await spec.handler(user_id, arguments)

        self.session.add(
            ToolCall(
                user_id=user_id,
                tool_name=name,
                arguments=arguments,
                result=result.model_dump(mode="json"),
                risk_level=result.risk_level,
                requires_confirmation=result.requires_confirmation,
            )
        )
        await self.session.flush()
        return result
