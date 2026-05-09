from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def today_in_timezone(timezone: str = "Asia/Shanghai") -> date:
    return datetime.now(ZoneInfo(timezone)).date()


def parse_chinese_date(text: str, today: date | None = None) -> date | None:
    today = today or date.today()
    normalized = text.strip()
    if "前天" in normalized:
        return today - timedelta(days=2)
    if "昨天" in normalized or "昨日" in normalized:
        return today - timedelta(days=1)
    if "今天" in normalized or "今日" in normalized:
        return today

    match = re.search(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?", normalized)
    if match:
        year, month, day = map(int, match.groups())
        return date(year, month, day)

    match = re.search(r"(\d{1,2})月(\d{1,2})日?", normalized)
    if match:
        month, day = map(int, match.groups())
        return date(today.year, month, day)

    return None


def month_range(anchor: date) -> tuple[date, date]:
    last_day = calendar.monthrange(anchor.year, anchor.month)[1]
    return date(anchor.year, anchor.month, 1), date(anchor.year, anchor.month, last_day)


def previous_month_range(anchor: date) -> tuple[date, date]:
    year = anchor.year
    month = anchor.month - 1
    if month == 0:
        year -= 1
        month = 12
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def week_range(anchor: date) -> tuple[date, date]:
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)


def previous_week_range(anchor: date) -> tuple[date, date]:
    current_start, _ = week_range(anchor)
    start = current_start - timedelta(days=7)
    return start, start + timedelta(days=6)
