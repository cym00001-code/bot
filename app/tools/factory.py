from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import Encryptor
from app.memory.service import MemoryService
from app.schemas import MemoryCandidate, ToolExecutionResult
from app.services.budget_service import BudgetService
from app.services.expense_service import ExpenseService
from app.services.reminder_service import ReminderService
from app.services.search_service import SearchService
from app.tools.base import ToolSpec
from app.tools.registry import ToolRegistry


def make_tool_registry(
    session: AsyncSession,
    settings: Settings,
    encryptor: Encryptor,
) -> ToolRegistry:
    registry = ToolRegistry(session)
    expense_service = ExpenseService(session, encryptor)
    budget_service = BudgetService(session, encryptor, expense_service)
    memory_service = MemoryService(session, encryptor)
    search_service = SearchService(settings)
    reminder_service = ReminderService(session, encryptor, settings.timezone)

    async def expense_record(user_id: UUID, args: dict) -> ToolExecutionResult:
        _, summary = await expense_service.record_from_text(user_id, str(args.get("text", "")))
        return ToolExecutionResult(
            tool_name="expense_record",
            arguments=args,
            risk_level="low",
            requires_confirmation=False,
            result_summary=summary,
            data={"ok": True},
        )

    async def expense_query(user_id: UUID, args: dict) -> ToolExecutionResult:
        _, summary, data = await expense_service.query_from_text(user_id, str(args.get("text", "")))
        data["total"] = str(data.get("total", "0"))
        return ToolExecutionResult(
            tool_name="expense_query",
            arguments=args,
            risk_level="low",
            requires_confirmation=False,
            result_summary=summary,
            data=data,
        )

    async def expense_delete(user_id: UUID, args: dict) -> ToolExecutionResult:
        _, summary = await expense_service.delete_from_text(user_id, str(args.get("text", "")))
        return ToolExecutionResult(
            tool_name="expense_delete",
            arguments=args,
            risk_level="medium",
            requires_confirmation=False,
            result_summary=summary,
            data={"ok": True},
        )

    async def budget_set(user_id: UUID, args: dict) -> ToolExecutionResult:
        _, summary = await budget_service.set_budget_from_text(user_id, str(args.get("text", "")))
        return ToolExecutionResult(
            tool_name="budget_set",
            arguments=args,
            risk_level="low",
            requires_confirmation=False,
            result_summary=summary,
            data={"ok": True},
        )

    async def budget_evaluate(user_id: UUID, args: dict) -> ToolExecutionResult:
        _, summary = await budget_service.evaluate_from_text(user_id, str(args.get("text", "")))
        return ToolExecutionResult(
            tool_name="budget_evaluate",
            arguments=args,
            risk_level="low",
            requires_confirmation=False,
            result_summary=summary,
            data={"ok": True},
        )

    async def memory_save(user_id: UUID, args: dict) -> ToolExecutionResult:
        content = str(args.get("content", "")).strip()
        memory_type = str(args.get("memory_type", "event"))
        if not content:
            return ToolExecutionResult(
                tool_name="memory_save",
                arguments=args,
                result_summary="没有可保存的记忆内容。",
                data={"ok": False},
            )
        candidate = MemoryCandidate(
            memory_type=memory_type,  # type: ignore[arg-type]
            content=content,
            confidence=float(args.get("confidence", 0.9)),
            source="tool",
        )
        saved = await memory_service.save_candidate(user_id, candidate)
        return ToolExecutionResult(
            tool_name="memory_save",
            arguments=args,
            risk_level="low",
            requires_confirmation=False,
            result_summary="已保存到长期记忆。" if saved else "这条记忆已经存在。",
            data={"ok": True, "saved": bool(saved)},
        )

    async def memory_forget(user_id: UUID, args: dict) -> ToolExecutionResult:
        keyword = str(args.get("keyword", "")).strip()
        if not keyword:
            return ToolExecutionResult(
                tool_name="memory_forget",
                arguments=args,
                risk_level="high",
                requires_confirmation=True,
                result_summary="请提供要删除的记忆关键词。",
                data={"ok": False},
            )
        count = await memory_service.forget_matching(user_id, keyword)
        return ToolExecutionResult(
            tool_name="memory_forget",
            arguments=args,
            risk_level="high",
            requires_confirmation=True,
            result_summary=f"已删除 {count} 条匹配记忆。",
            data={"ok": True, "deleted": count},
        )

    async def web_search(user_id: UUID, args: dict) -> ToolExecutionResult:
        query = str(args.get("query", "")).strip()
        result = await search_service.search(query)
        return ToolExecutionResult(
            tool_name="web_search",
            arguments=args,
            risk_level="low",
            requires_confirmation=False,
            result_summary=result["summary"],
            data=result,
        )

    async def reminder_create(user_id: UUID, args: dict) -> ToolExecutionResult:
        _, summary = await reminder_service.create_from_text(user_id, str(args.get("text", "")))
        return ToolExecutionResult(
            tool_name="reminder_create",
            arguments=args,
            risk_level="low",
            requires_confirmation=False,
            result_summary=summary,
            data={"ok": True},
        )

    async def reminder_list(user_id: UUID, args: dict) -> ToolExecutionResult:
        summary = await reminder_service.list_pending(user_id)
        return ToolExecutionResult(
            tool_name="reminder_list",
            arguments=args,
            risk_level="low",
            requires_confirmation=False,
            result_summary=summary,
            data={"ok": True},
        )

    async def reminder_complete(user_id: UUID, args: dict) -> ToolExecutionResult:
        _, summary = await reminder_service.complete_from_text(user_id, str(args.get("text", "")))
        return ToolExecutionResult(
            tool_name="reminder_complete",
            arguments=args,
            risk_level="low",
            requires_confirmation=False,
            result_summary=summary,
            data={"ok": True},
        )

    text_arg_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    registry.register(
        ToolSpec(
            name="expense_record",
            description="记录一笔自然语言花销或收入，例如：昨天打车 42.8。",
            parameters=text_arg_schema,
            risk_level="low",
            requires_confirmation=False,
            handler=expense_record,
        )
    )
    registry.register(
        ToolSpec(
            name="expense_query",
            description="查询花销统计，例如：这个月餐饮花了多少。",
            parameters=text_arg_schema,
            risk_level="low",
            requires_confirmation=False,
            handler=expense_query,
        )
    )
    registry.register(
        ToolSpec(
            name="expense_delete",
            description="删除一笔账单，例如：删除上一笔，或 删除今天午饭36。",
            parameters=text_arg_schema,
            risk_level="medium",
            requires_confirmation=False,
            handler=expense_delete,
        )
    )
    registry.register(
        ToolSpec(
            name="budget_set",
            description="设置本月预算，例如：这个月预算3000，本月餐饮预算800。",
            parameters=text_arg_schema,
            risk_level="low",
            requires_confirmation=False,
            handler=budget_set,
        )
    )
    registry.register(
        ToolSpec(
            name="budget_evaluate",
            description="评估一笔计划消费是否适合当前预算，例如：想花200买鞋，帮我评估。",
            parameters=text_arg_schema,
            risk_level="low",
            requires_confirmation=False,
            handler=budget_evaluate,
        )
    )
    registry.register(
        ToolSpec(
            name="memory_save",
            description="保存一条用户明确表达的长期记忆。",
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "memory_type": {
                        "type": "string",
                        "enum": [
                            "profile",
                            "preference",
                            "relationship",
                            "event",
                            "finance",
                            "project",
                            "instruction",
                        ],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["content", "memory_type"],
            },
            risk_level="low",
            requires_confirmation=False,
            handler=memory_save,
        )
    )
    registry.register(
        ToolSpec(
            name="memory_forget",
            description="按关键词删除长期记忆。高风险操作，必须用户确认。",
            parameters={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "confirmed": {"type": "boolean"},
                },
                "required": ["keyword"],
            },
            risk_level="high",
            requires_confirmation=True,
            handler=memory_forget,
        )
    )
    registry.register(
        ToolSpec(
            name="web_search",
            description="通过自托管 SearXNG 搜索公开网页，适合需要最新信息的问题。",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            risk_level="low",
            requires_confirmation=False,
            handler=web_search,
        )
    )
    registry.register(
        ToolSpec(
            name="reminder_create",
            description="创建提醒，例如：明天9点提醒我交水费。",
            parameters=text_arg_schema,
            risk_level="low",
            requires_confirmation=False,
            handler=reminder_create,
        )
    )
    registry.register(
        ToolSpec(
            name="reminder_list",
            description="列出当前待办和提醒。",
            parameters={"type": "object", "properties": {}},
            risk_level="low",
            requires_confirmation=False,
            handler=reminder_list,
        )
    )
    registry.register(
        ToolSpec(
            name="reminder_complete",
            description="完成一个待办或提醒，例如：完成交水费待办。",
            parameters=text_arg_schema,
            risk_level="low",
            requires_confirmation=False,
            handler=reminder_complete,
        )
    )
    return registry
