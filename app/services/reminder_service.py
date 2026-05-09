from __future__ import annotations

import re
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Encryptor
from app.db.models import Reminder


class ReminderService:
    def __init__(self, session: AsyncSession, encryptor: Encryptor, timezone: str) -> None:
        self.session = session
        self.encryptor = encryptor
        self.timezone = timezone

    async def create_from_text(self, user_id: UUID, text: str) -> tuple[Reminder | None, str]:
        parsed = self._parse_due_at_and_content(text)
        if parsed is None:
            return None, "我还没识别出提醒时间。可以说：明天9点提醒我交水费。"
        due_at, content = parsed
        reminder = Reminder(
            user_id=user_id,
            due_at=due_at,
            content_encrypted=self.encryptor.encrypt_text(content) or "",
        )
        self.session.add(reminder)
        await self.session.flush()
        return reminder, f"已设置提醒：{due_at:%Y-%m-%d %H:%M}，{content}"

    async def due_reminders(self, now: datetime) -> list[Reminder]:
        return (
            await self.session.scalars(
                select(Reminder).where(
                    and_(Reminder.status == "pending", Reminder.due_at <= now)
                )
            )
        ).all()

    async def mark_sent(self, reminder_id: UUID) -> None:
        await self.session.execute(
            update(Reminder)
            .where(Reminder.id == reminder_id)
            .values(status="sent", sent_at=datetime.now(ZoneInfo(self.timezone)))
        )

    def decrypt_content(self, reminder: Reminder) -> str:
        return self.encryptor.decrypt_text(reminder.content_encrypted) or ""

    def _parse_due_at_and_content(self, text: str) -> tuple[datetime, str] | None:
        if "提醒" not in text:
            return None

        now = datetime.now(ZoneInfo(self.timezone))
        day = now.date()
        if "后天" in text:
            day = day + timedelta(days=2)
        elif "明天" in text:
            day = day + timedelta(days=1)
        elif "今天" in text:
            day = day
        else:
            return None

        hour = 9
        minute = 0
        time_match = re.search(r"(\d{1,2})(?:点|:)(\d{1,2})?", text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)

        content = text.split("提醒", 1)[-1]
        content = re.sub(r"我|一下|下|[:：]", "", content).strip(" ，,。.")
        if not content:
            content = "该处理提醒事项了"
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(self.timezone)), content
