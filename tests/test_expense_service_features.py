from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.security import Encryptor
from app.db.models import Expense
from app.services.expense_service import ExpenseService


class ScalarResult:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.executed = []
        self.flushed = False

    async def scalars(self, statement):
        return ScalarResult(self.rows)

    async def execute(self, statement):
        self.executed.append(statement)

    async def flush(self) -> None:
        self.flushed = True


def make_expense(encryptor: Encryptor, amount: str, category: str, note: str) -> Expense:
    return Expense(
        id=uuid4(),
        user_id=uuid4(),
        occurred_on=date(2026, 5, 10),
        amount=Decimal(amount),
        category=category,
        note_encrypted=encryptor.encrypt_text(note),
        created_at=datetime(2026, 5, 10, 12, 0),
    )


@pytest.mark.asyncio
async def test_recent_expense_list_formats_numbered_rows() -> None:
    encryptor = Encryptor("test")
    session = FakeSession([make_expense(encryptor, "36", "餐饮", "午饭")])
    service = ExpenseService(session, encryptor)  # type: ignore[arg-type]

    summary = await service.list_recent(uuid4())

    assert "最近账单" in summary
    assert "1. 05-10 餐饮 36.00 元，午饭" in summary


@pytest.mark.asyncio
async def test_update_previous_expense_can_change_category() -> None:
    encryptor = Encryptor("test")
    session = FakeSession([make_expense(encryptor, "36", "其他", "午饭")])
    service = ExpenseService(session, encryptor)  # type: ignore[arg-type]

    count, summary = await service.update_from_text(uuid4(), "把上一笔改成餐饮")

    assert count == 1
    assert "改好了" in summary
    assert "餐饮" in summary
    assert session.executed
    assert session.flushed


def test_expense_feature_intent_detection() -> None:
    service = ExpenseService(None, Encryptor("test"))  # type: ignore[arg-type]

    assert service.looks_like_recent_list("最近10笔账单")
    assert service.looks_like_update("把上一笔改成餐饮")
    assert service.looks_like_breakdown("这个月消费结构怎么样")
