from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import Settings
from app.core.security import Encryptor
from app.db.models import User
from app.db.session import AsyncSessionLocal
from app.gateways.wecom import WeComGateway
from app.memory.service import MemoryService
from app.services.expense_service import ExpenseService
from app.services.reminder_service import ReminderService

logger = logging.getLogger(__name__)


def build_scheduler(settings: Settings, encryptor: Encryptor, wecom: WeComGateway) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)

    async def send_daily_summary() -> None:
        async with AsyncSessionLocal() as session:
            owner = await session.scalar(select(User).where(User.is_owner.is_(True)))
            if not owner:
                return
            summary = await ExpenseService(session, encryptor).daily_summary(owner.id)
            await wecom.send_text(owner.wecom_user_id, summary)

    async def send_weekly_memory_review() -> None:
        async with AsyncSessionLocal() as session:
            owner = await session.scalar(select(User).where(User.is_owner.is_(True)))
            if not owner:
                return
            memories = await MemoryService(session, encryptor).retrieve(owner.id, "最近重要记忆", limit=10)
            if not memories:
                return
            lines = "\n".join(f"- {memory.content}" for memory in memories)
            await wecom.send_text(owner.wecom_user_id, f"本周记忆回顾：\n{lines}\n\n需要删除哪条，直接说“删除关于 xxx 的记忆”。")

    async def send_due_reminders() -> None:
        now = datetime.now(ZoneInfo(settings.timezone))
        async with AsyncSessionLocal() as session:
            owner = await session.scalar(select(User).where(User.is_owner.is_(True)))
            if not owner:
                return
            service = ReminderService(session, encryptor, settings.timezone)
            reminders = await service.due_reminders(now)
            for reminder in reminders:
                content = service.decrypt_content(reminder)
                sent = await wecom.send_text(owner.wecom_user_id, f"提醒：{content}")
                if sent:
                    await service.mark_sent(reminder.id)
            await session.commit()

    scheduler.add_job(send_due_reminders, "interval", minutes=1, id="due_reminders")
    scheduler.add_job(
        send_daily_summary,
        "cron",
        hour=settings.daily_summary_hour,
        minute=0,
        id="daily_summary",
    )
    scheduler.add_job(
        send_weekly_memory_review,
        "cron",
        day_of_week=settings.weekly_memory_review_day,
        hour=settings.weekly_memory_review_hour,
        minute=0,
        id="weekly_memory_review",
    )
    return scheduler
