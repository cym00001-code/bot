from __future__ import annotations

from app.core.security import Encryptor
from app.services.reminder_service import ReminderService


def test_parse_tomorrow_reminder() -> None:
    service = ReminderService(None, Encryptor("test"), "Asia/Shanghai")  # type: ignore[arg-type]

    parsed = service._parse_due_at_and_content("明天9点提醒我交水费")

    assert parsed is not None
    due_at, content = parsed
    assert due_at.hour == 9
    assert due_at.minute == 0
    assert content == "交水费"


def test_parse_relative_reminder() -> None:
    service = ReminderService(None, Encryptor("test"), "Asia/Shanghai")  # type: ignore[arg-type]

    parsed = service._parse_due_at_and_content("30分钟后提醒我出门")

    assert parsed is not None
    _, content = parsed
    assert content == "出门"
