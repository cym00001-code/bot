from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Encryptor
from app.db.models import Reminder
from app.utils.dates import parse_chinese_date


class ReminderService:
    def __init__(self, session: AsyncSession, encryptor: Encryptor, timezone: str) -> None:
        self.session = session
        self.encryptor = encryptor
        self.timezone = timezone

    async def create_from_text(self, user_id: UUID, text: str) -> tuple[Reminder | None, str]:
        parsed = self._parse_due_at_and_content(text)
        if parsed is None:
            return None, "时间也给我一下，比如：明天9点提醒我交水费，或 30分钟后提醒我出门。"
        due_at, content = parsed
        reminder = Reminder(
            user_id=user_id,
            due_at=due_at,
            content_encrypted=self.encryptor.encrypt_text(content) or "",
        )
        self.session.add(reminder)
        await self.session.flush()
        return reminder, f"行，{due_at:%Y-%m-%d %H:%M} 提醒你：{content}"

    async def list_pending(self, user_id: UUID, limit: int = 8) -> str:
        rows = (
            await self.session.scalars(
                select(Reminder)
                .where(Reminder.user_id == user_id, Reminder.status == "pending")
                .order_by(Reminder.due_at.asc())
                .limit(limit)
            )
        ).all()
        if not rows:
            return "现在没有待办。"
        lines = [
            f"- {row.due_at:%m-%d %H:%M} {self.decrypt_content(row)}"
            for row in rows
        ]
        return "你的待办：\n" + "\n".join(lines)

    async def complete_from_text(self, user_id: UUID, text: str) -> tuple[int, str]:
        keyword = self._extract_complete_keyword(text)
        rows = (
            await self.session.scalars(
                select(Reminder)
                .where(Reminder.user_id == user_id, Reminder.status == "pending")
                .order_by(Reminder.due_at.asc())
                .limit(20)
            )
        ).all()
        matched = [
            row
            for row in rows
            if not keyword or keyword in self.decrypt_content(row)
        ]
        if not matched:
            return 0, "没找到这个待办。你可以说：我的待办。"
        if len(matched) > 1 and keyword:
            return 0, "匹配到不止一个，关键词再具体一点。"
        target = matched[0]
        await self.session.execute(
            update(Reminder)
            .where(Reminder.id == target.id)
            .values(status="done", sent_at=datetime.now(ZoneInfo(self.timezone)))
        )
        return 1, f"完成了：{self.decrypt_content(target)}"

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
        if "提醒" not in text and "待办" not in text and "todo" not in text.lower():
            return None

        now = datetime.now(ZoneInfo(self.timezone))
        relative_due = self._parse_relative_due(text, now)
        if relative_due:
            due_at = relative_due
        else:
            day = self._parse_day(text, now.date())
            if day is None:
                return None
            reminder_time = self._parse_time(text)
            if reminder_time is None:
                reminder_time = time(20, 0) if "晚上" in text or "今晚" in text else time(9, 0)
            due_at = datetime.combine(day, reminder_time, tzinfo=ZoneInfo(self.timezone))
            if due_at <= now:
                due_at += timedelta(days=1)

        content = self._clean_content(text)
        if not content:
            content = "该处理提醒事项了"
        return due_at, content

    def _parse_relative_due(self, text: str, now: datetime) -> datetime | None:
        if "半小时后" in text:
            return now + timedelta(minutes=30)
        minute_match = re.search(r"(\d+)\s*分钟后", text)
        if minute_match:
            return now + timedelta(minutes=int(minute_match.group(1)))
        hour_match = re.search(r"(\d+(?:\.\d+)?)\s*小时后", text)
        if hour_match:
            return now + timedelta(hours=float(hour_match.group(1)))
        return None

    def _parse_day(self, text: str, today: date) -> date | None:
        if "后天" in text:
            return today + timedelta(days=2)
        if "明天" in text:
            return today + timedelta(days=1)
        if "今天" in text or "今晚" in text:
            return today
        parsed = parse_chinese_date(text, today=today)
        if parsed:
            return parsed
        weekday_match = re.search(r"(?:周|星期)([一二三四五六日天1-7])", text)
        if weekday_match:
            weekday_map = {
                "一": 0,
                "1": 0,
                "二": 1,
                "2": 1,
                "三": 2,
                "3": 2,
                "四": 3,
                "4": 3,
                "五": 4,
                "5": 4,
                "六": 5,
                "6": 5,
                "日": 6,
                "天": 6,
                "7": 6,
            }
            target = weekday_map[weekday_match.group(1)]
            delta = (target - today.weekday()) % 7
            return today + timedelta(days=delta or 7)
        return None

    def _parse_time(self, text: str) -> time | None:
        colon_match = re.search(r"(\d{1,2})[:：](\d{1,2})", text)
        if colon_match:
            hour, minute = int(colon_match.group(1)), int(colon_match.group(2))
        else:
            time_match = re.search(r"(\d{1,2})点(?:(半)|(\d{1,2})分?)?", text)
            if not time_match:
                return None
            hour = int(time_match.group(1))
            minute = 30 if time_match.group(2) else int(time_match.group(3) or 0)
        if any(word in text for word in ("下午", "晚上", "今晚")) and hour < 12:
            hour += 12
        if hour > 23 or minute > 59:
            return None
        return time(hour, minute)

    def _clean_content(self, text: str) -> str:
        content = text
        content = re.sub(r"(?:\d+(?:\.\d+)?\s*小时后|\d+\s*分钟后|半小时后)", " ", content)
        content = re.sub(r"(?:今天|明天|后天|今晚|上午|下午|晚上|早上)", " ", content)
        content = re.sub(r"\d{4}[年/-]\d{1,2}[月/-]\d{1,2}日?", " ", content)
        content = re.sub(r"\d{1,2}月\d{1,2}日?", " ", content)
        content = re.sub(r"(?:周|星期)[一二三四五六日天1-7]", " ", content)
        content = re.sub(r"\d{1,2}[:：]\d{1,2}", " ", content)
        content = re.sub(r"\d{1,2}点(?:(?:半)|(?:\d{1,2}分?)?)?", " ", content)
        content = re.sub(r"(?:提醒我|提醒|待办|todo|帮我|我|一下|下|[:：])", " ", content, flags=re.I)
        return re.sub(r"\s+", " ", content).strip(" ，,。.")

    def _extract_complete_keyword(self, text: str) -> str:
        keyword = re.sub(r"(完成|做完了|搞定了|取消|删掉|删除|待办|提醒)", " ", text)
        return re.sub(r"\s+", " ", keyword).strip(" ，,。.")
