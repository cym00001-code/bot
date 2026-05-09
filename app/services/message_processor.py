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
from app.schemas import ChatContext, IncomingMessage
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

        shortcut = await self._try_local_shortcut(user.id, incoming.content)
        if shortcut:
            await self._save_message(user.id, "out", shortcut)
            return shortcut

        memory_service = MemoryService(self.session, self.encryptor)
        await memory_service.remember_from_text(user.id, incoming.content)
        memories = await memory_service.retrieve(user.id, incoming.content, limit=8)
        recent_messages = await self._recent_messages(user.id)
        if (
            recent_messages
            and recent_messages[-1]["role"] == "user"
            and recent_messages[-1]["content"] == incoming.content
        ):
            recent_messages = recent_messages[:-1]

        context = ChatContext(
            user_id=user.id,
            user_text=incoming.content,
            memories=[f"{item.memory_type}: {item.content}" for item in memories],
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

        if self.expense_parser.parse_record(text, today=today):
            _, summary = await expense_service.record_from_text(user_id, text, today=today)
            return summary

        if self.expense_parser.parse_query(text, today=today):
            _, summary, _ = await expense_service.query_from_text(user_id, text, today=today)
            return summary

        if "提醒" in text and any(word in text for word in ("今天", "明天", "后天")):
            _, summary = await ReminderService(
                self.session, self.encryptor, self.settings.timezone
            ).create_from_text(user_id, text)
            return summary

        return None

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
