from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ToolCall
from app.services.pending_action_service import PendingActionService
from app.schemas import ToolExecutionResult
from app.tools.base import ToolSpec


class ToolRegistry:
    def __init__(self, session: AsyncSession, timezone: str = "Asia/Shanghai") -> None:
        self.session = session
        self.pending_actions = PendingActionService(session, timezone)
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def list_for_model(self, names: set[str] | None = None) -> list[dict[str, Any]]:
        tools = self._tools.values()
        if names is not None:
            tools = [tool for tool in tools if tool.name in names]
        return [tool.as_deepseek_tool() for tool in tools]

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
            prompt = self._confirmation_prompt(spec, arguments)
            await self.pending_actions.create_or_replace(
                user_id=user_id,
                tool_name=name,
                arguments=arguments,
                risk_level=spec.risk_level,
                prompt=prompt,
            )
            result = ToolExecutionResult(
                tool_name=name,
                arguments=arguments,
                risk_level=spec.risk_level,
                requires_confirmation=True,
                result_summary=prompt,
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

    async def execute_confirmed_pending(self, user_id: UUID) -> ToolExecutionResult | None:
        action = await self.pending_actions.latest_pending(user_id)
        if action is None:
            return None
        arguments = dict(action.arguments)
        arguments["confirmed"] = True
        result = await self.execute(action.tool_name, user_id=user_id, arguments=arguments)
        await self.pending_actions.mark_done(action)
        return result

    async def cancel_pending(self, user_id: UUID) -> bool:
        return await self.pending_actions.cancel_latest(user_id)

    async def latest_confirmation_prompt(self, user_id: UUID) -> str | None:
        action = await self.pending_actions.latest_pending(user_id)
        return action.prompt if action else None

    def looks_like_confirm(self, text: str) -> bool:
        return self.pending_actions.looks_like_confirm(text)

    def looks_like_cancel(self, text: str) -> bool:
        return self.pending_actions.looks_like_cancel(text)

    def _confirmation_prompt(self, spec: ToolSpec, arguments: dict[str, Any]) -> str:
        details = ""
        if "keyword" in arguments:
            details = f"关键词：{arguments['keyword']}"
        elif "text" in arguments:
            details = f"内容：{arguments['text']}"
        if details:
            return f"这个操作风险较高，需要你回复“确认”才会执行。\n{details}"
        return "这个操作风险较高，需要你回复“确认”才会执行。"
