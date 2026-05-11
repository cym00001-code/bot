from __future__ import annotations

import logging
import re
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
from app.services.pending_action_service import PendingActionService
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
        if await self._is_duplicate_message(incoming):
            logger.info("ignored duplicate WeCom message: %s", incoming.message_id)
            return ""
        await self._save_message(user.id, "in", incoming.content, incoming)
        memory_service = MemoryService(self.session, self.encryptor)
        registry = make_tool_registry(self.session, self.settings, self.encryptor)
        pending_reply = await self._try_pending_action(user.id, incoming.content, registry)
        if pending_reply:
            await self._save_message(user.id, "out", pending_reply)
            return pending_reply

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
            memories = await self._memories_for_recall(memory_service, user.id, incoming.content)
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
        reply = await DeepSeekBrain(self.settings).answer(context, registry)
        await self._save_message(user.id, "out", reply)
        return reply

    async def _try_pending_action(self, user_id: UUID, text: str, registry) -> str | None:
        if registry.looks_like_cancel(text):
            cancelled = await registry.cancel_pending(user_id)
            return "行，已取消上一条待确认操作。" if cancelled else None
        if registry.looks_like_confirm(text):
            result = await registry.execute_confirmed_pending(user_id)
            if result is None:
                return None
            return result.result_summary
        pending = await registry.latest_confirmation_prompt(user_id)
        if pending and any(word in text for word in ("确认什么", "要确认什么", "刚才")):
            return pending
        return None

    async def _try_local_shortcut(self, user_id: UUID, text: str) -> str | None:
        today = today_in_timezone(self.settings.timezone)
        expense_service = ExpenseService(self.session, self.encryptor, self.expense_parser)
        budget_service = BudgetService(self.session, self.encryptor, expense_service, self.expense_parser)
        reminder_service = ReminderService(self.session, self.encryptor, self.settings.timezone)
        pending_actions = PendingActionService(self.session, self.settings.timezone)

        memory_reply = await self._try_memory_management(user_id, text)
        if memory_reply:
            return memory_reply

        if expense_service.looks_like_recent_list(text):
            return await expense_service.list_recent(user_id)

        if expense_service.looks_like_update(text):
            _, summary = await expense_service.update_from_text(user_id, text, today=today)
            return summary

        if expense_service.looks_like_breakdown(text):
            return await expense_service.category_breakdown_from_text(user_id, text, today=today)

        if self.expense_parser.looks_like_delete(text):
            preview = await expense_service.preview_delete_from_text(user_id, text, today=today)
            if preview is None:
                return "没找到能确定删除的那笔。你可以说：删除上一笔，或 删除今天午饭36。"
            _, summary = preview
            prompt = f"{summary}\n回复“确认”我再删除。"
            await pending_actions.create_or_replace(
                user_id=user_id,
                tool_name="expense_delete",
                arguments={"text": text},
                risk_level="medium",
                prompt=prompt,
            )
            return prompt

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
                "最近记忆",
                "记忆列表",
            )
        )

    def _format_memory_recall(self, memories: list[RetrievedMemory]) -> str:
        if not memories:
            return "现在还没记下太多。你可以直接说“记住……”，我会存起来。"
        lines = [f"{index}. {memory.content}" for index, memory in enumerate(memories[:10], start=1)]
        return "我现在记得这些：\n" + "\n".join(lines)

    async def _memories_for_recall(
        self, memory_service: MemoryService, user_id: UUID, text: str
    ) -> list[RetrievedMemory]:
        if any(phrase in text for phrase in ("最近记忆", "记忆列表")):
            return await memory_service.list_recent(user_id, limit=10)
        return await memory_service.retrieve(
            user_id, text, limit=min(self.settings.memory_retrieval_limit, 8)
        )

    async def _try_memory_management(self, user_id: UUID, text: str) -> str | None:
        memory_service = MemoryService(self.session, self.encryptor)
        if "整理我的记忆" in text or "整理一下记忆" in text:
            return await memory_service.organize_summary(user_id)

        index_match = re.search(r"(?:删除|删掉|忘掉)(?:第)?\s*(\d+)\s*(?:条|个)?(?:记忆)?", text)
        if index_match:
            index = int(index_match.group(1))
            memories = await memory_service.list_recent(user_id, limit=10)
            if index < 1 or index > len(memories):
                return "没找到这个序号。你可以先说：最近记忆。"
            target = memories[index - 1]
            pending_actions = PendingActionService(self.session, self.settings.timezone)
            prompt = f"准备删除这条记忆：{target.content}\n回复“确认”我再删除。"
            await pending_actions.create_or_replace(
                user_id=user_id,
                tool_name="memory_forget",
                arguments={"memory_id": str(target.id)},
                risk_level="high",
                prompt=prompt,
            )
            return prompt

        keyword_match = re.search(r"(?:删除|删掉|忘掉|清除)(?:关于)?\s*(?P<keyword>.+?)(?:的)?记忆?$", text)
        if keyword_match:
            keyword = keyword_match.group("keyword").strip(" ，,。.")
            if keyword:
                pending_actions = PendingActionService(self.session, self.settings.timezone)
                prompt = f"准备删除包含“{keyword}”的记忆。\n回复“确认”我再删除。"
                await pending_actions.create_or_replace(
                    user_id=user_id,
                    tool_name="memory_forget",
                    arguments={"keyword": keyword},
                    risk_level="high",
                    prompt=prompt,
                )
                return prompt

        return None

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
                external_message_id=incoming.message_id if incoming else None,
                content_encrypted=self.encryptor.encrypt_text(content),
                raw_payload=incoming.raw_payload if incoming else None,
            )
        )
        await self.session.flush()

    async def _is_duplicate_message(self, incoming: IncomingMessage) -> bool:
        if not incoming.message_id:
            return False
        existing = await self.session.scalar(
            select(Message.id).where(
                Message.channel == "wecom",
                Message.external_message_id == incoming.message_id,
            )
        )
        return existing is not None

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
