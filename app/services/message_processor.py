from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.deepseek import DeepSeekBrain
from app.core.config import Settings
from app.core.security import Encryptor
from app.db.models import Message, User
from app.memory.service import MemoryService
from app.schemas import ChatContext, IncomingMessage, RetrievedMemory
from app.services.budget_service import BudgetService
from app.services.expense_parser import ExpenseParser
from app.services.expense_service import ExpenseService
from app.services.reminder_service import ReminderService
from app.tools.factory import make_tool_registry
from app.utils.dates import today_in_timezone

logger = logging.getLogger(__name__)


class UnauthorizedUserError(PermissionError):
    pass


class MessageProcessor:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        encryptor: Encryptor,
    ) -> None:
        self.session = session
        self.settings = settings
        self.encryptor = encryptor
        self.expense_parser = ExpenseParser()

    async def process(self, incoming: IncomingMessage) -> str:
        user = await self._ensure_owner_user(incoming.sender_id)
        await self._save_message(user.id, "in", incoming.content, incoming)
        memory_service = MemoryService(self.session, self.encryptor)
        saved_memories = await memory_service.remember_from_text(user.id, incoming.content)

        memory_shortcut = self._memory_shortcut_reply(incoming.content, saved_memories)
        if memory_shortcut:
            await self._save_message(user.id, "out", memory_shortcut)
            return memory_shortcut

        shortcut = await self._try_local_shortcut(user.id, incoming.content)
        if shortcut:
            await self._save_message(user.id, "out", shortcut)
            return shortcut

        if self._is_memory_recall_query(incoming.content):
            memories = await memory_service.retrieve(
                user.id, incoming.content, limit=min(self.settings.memory_retrieval_limit, 8)
            )
            reply = self._format_memory_recall(memories)
            await self._save_message(user.id, "out", reply)
            return reply

        memories = await memory_service.retrieve(
            user.id, incoming.content, limit=self.settings.memory_retrieval_limit
        )
        recent_messages = await self._recent_messages(user.id, limit=self.settings.recent_message_limit)
        if (
            recent_messages
            and recent_messages[-1]["role"] == "user"
            and recent_messages[-1]["content"] == incoming.content
        ):
            recent_messages = recent_messages[:-1]

        context = ChatContext(
            user_id=user.id,
            user_text=incoming.content,
            memories=self._memory_context_lines(memories),
            recent_messages=recent_messages,
            now=datetime.now(ZoneInfo(self.settings.timezone)),
        )
        registry = make_tool_registry(self.session, self.settings, self.encryptor)
        reply = await DeepSeekBrain(self.settings).answer(context, registry)
        await self._save_message(user.id, "out", reply)
        return reply

    async def _try_local_shortcut(self, user_id: UUID, text: str) -> str | None:
        today = today_in_timezone(self.settings.timezone)
        expense_service = ExpenseService(self.session, self.encryptor, self.expense_parser)
        budget_service = BudgetService(self.session, self.encryptor, expense_service, self.expense_parser)
        reminder_service = ReminderService(self.session, self.encryptor, self.settings.timezone)

        if self.expense_parser.looks_like_delete(text):
            _, summary = await expense_service.delete_from_text(user_id, text, today=today)
            return summary

        if self.expense_parser.parse_query(text, today=today):
            _, summary, _ = await expense_service.query_from_text(user_id, text, today=today)
            return summary

        budget_summary = await budget_service.summary_from_text(user_id, text, today=today)
        if budget_summary:
            return budget_summary

        if budget_service.parse_spend_evaluation(text, today=today):
            _, summary = await budget_service.evaluate_from_text(user_id, text, today=today)
            return summary

        if budget_service.parse_budget(text, today=today):
            _, summary = await budget_service.set_budget_from_text(user_id, text, today=today)
            return summary

        if self._looks_like_reminder_list(text):
            return await reminder_service.list_pending(user_id)

        if self._looks_like_reminder_done(text):
            _, summary = await reminder_service.complete_from_text(user_id, text)
            return summary

        if self._looks_like_reminder_create(text):
            _, summary = await reminder_service.create_from_text(user_id, text)
            return summary

        if self.expense_parser.parse_record(text, today=today):
            _, summary = await expense_service.record_from_text(user_id, text, today=today)
            return summary

        return None

    def _memory_shortcut_reply(
        self, text: str, saved_memories: list[RetrievedMemory]
    ) -> str | None:
        if not saved_memories:
            return None
        if not any(word in text for word in ("记住", "记一下", "别忘", "以后你要")):
            return None
        if len(text) > 160:
            return None
        joined = "；".join(memory.content for memory in saved_memories[:3])
        return f"记下了：{joined}"

    def _memory_context_lines(self, memories: list[RetrievedMemory]) -> list[str]:
        lines: list[str] = []
        used = 0
        for item in memories:
            content = item.content.strip()
            if len(content) > self.settings.memory_item_char_limit:
                content = content[: self.settings.memory_item_char_limit - 1] + "…"
            line = f"{item.memory_type}: {content}"
            if used + len(line) > self.settings.memory_context_char_budget:
                break
            lines.append(line)
            used += len(line)
        return lines

    def _is_memory_recall_query(self, text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "你记得我什么",
                "你都记得什么",
                "你知道我什么",
                "我的记忆",
                "我喜欢什么",
                "我有什么偏好",
                "我的偏好",
            )
        )

    def _format_memory_recall(self, memories: list[RetrievedMemory]) -> str:
        if not memories:
            return "现在还没记下太多。你可以直接说“记住……”，我会存起来。"
        lines = [f"- {memory.content}" for memory in memories[:8]]
        return "我现在记得这些：\n" + "\n".join(lines)

    def _looks_like_reminder_create(self, text: str) -> bool:
        return "提醒" in text or "待办" in text or "todo" in text.lower()

    def _looks_like_reminder_list(self, text: str) -> bool:
        return any(phrase in text for phrase in ("我的待办", "待办列表", "有什么待办", "提醒列表"))

    def _looks_like_reminder_done(self, text: str) -> bool:
        return any(word in text for word in ("完成", "做完了", "搞定了"))

    async def _ensure_owner_user(self, sender_id: str) -> User:
        owner_id = self.settings.owner_we_com_user_id.strip()
        if owner_id and sender_id != owner_id:
            raise UnauthorizedUserError(f"sender {sender_id} is not the configured owner")

        user = await self.session.scalar(select(User).where(User.wecom_user_id == sender_id))
        if user:
            return user
        user = User(wecom_user_id=sender_id, display_name=sender_id, is_owner=True)
        self.session.add(user)
        await self.session.flush()
        return user

    async def _save_message(
        self,
        user_id: UUID,
        direction: str,
        content: str,
        incoming: IncomingMessage | None = None,
    ) -> None:
        self.session.add(
            Message(
                user_id=user_id,
                direction=direction,
                channel="wecom",
                message_type=incoming.message_type if incoming else "text",
                content_encrypted=self.encryptor.encrypt_text(content),
                raw_payload=incoming.raw_payload if incoming else None,
            )
        )
        await self.session.flush()

    async def _recent_messages(self, user_id: UUID, limit: int = 10) -> list[dict[str, str]]:
        rows = (
            await self.session.scalars(
                select(Message)
                .where(Message.user_id == user_id)
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
        ).all()
        messages: list[dict[str, str]] = []
        for row in reversed(rows):
            content = self.encryptor.decrypt_text(row.content_encrypted) or ""
            if not content:
                continue
            role = "assistant" if row.direction == "out" else "user"
            messages.append({"role": role, "content": content})
        return messages
