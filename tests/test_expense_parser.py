from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.expense_parser import ExpenseParser


def test_parse_simple_expense_record() -> None:
    parser = ExpenseParser()
    intent = parser.parse_record("午饭 36", today=date(2026, 5, 9))

    assert intent is not None
    assert intent.amount == Decimal("36")
    assert intent.category == "餐饮"
    assert intent.occurred_on == date(2026, 5, 9)
    assert intent.note == "午饭"


def test_parse_yesterday_transport_record() -> None:
    parser = ExpenseParser()
    intent = parser.parse_record("昨天打车 42.8", today=date(2026, 5, 9))

    assert intent is not None
    assert intent.amount == Decimal("42.8")
    assert intent.category == "交通"
    assert intent.occurred_on == date(2026, 5, 8)


def test_parse_month_category_query() -> None:
    parser = ExpenseParser()
    intent = parser.parse_query("这个月餐饮花了多少", today=date(2026, 5, 9))

    assert intent is not None
    assert intent.start_on == date(2026, 5, 1)
    assert intent.end_on == date(2026, 5, 31)
    assert intent.category == "餐饮"


def test_query_is_not_misread_as_record() -> None:
    parser = ExpenseParser()

    assert parser.parse_record("这个月餐饮花了多少", today=date(2026, 5, 9)) is None
