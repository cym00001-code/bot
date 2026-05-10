from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.security import Encryptor
from app.services.budget_service import BudgetService


def test_parse_month_budget() -> None:
    service = BudgetService(None, Encryptor("test"))  # type: ignore[arg-type]

    intent = service.parse_budget("这个月预算3000", today=date(2026, 5, 10))

    assert intent is not None
    assert intent.month == date(2026, 5, 1)
    assert intent.amount == Decimal("3000")
    assert intent.category is None


def test_parse_category_budget() -> None:
    service = BudgetService(None, Encryptor("test"))  # type: ignore[arg-type]

    intent = service.parse_budget("本月餐饮预算800", today=date(2026, 5, 10))

    assert intent is not None
    assert intent.category == "餐饮"


def test_parse_spend_evaluation() -> None:
    service = BudgetService(None, Encryptor("test"))  # type: ignore[arg-type]

    intent = service.parse_spend_evaluation("想花 200 买鞋，帮我评估", today=date(2026, 5, 10))

    assert intent is not None
    assert intent.amount == Decimal("200")
    assert intent.category == "购物"
