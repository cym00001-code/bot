from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Encryptor
from app.db.models import Expense
from app.schemas import ExpenseQueryIntent, ExpenseRecordIntent
from app.services.expense_parser import ExpenseParser


class ExpenseService:
    def __init__(
        self,
        session: AsyncSession,
        encryptor: Encryptor,
        parser: ExpenseParser | None = None,
    ) -> None:
        self.session = session
        self.encryptor = encryptor
        self.parser = parser or ExpenseParser()

    async def record_from_text(
        self, user_id: UUID, text: str, today: date | None = None
    ) -> tuple[Expense | None, str]:
        intent = self.parser.parse_record(text, today=today)
        if intent is None:
            return None, "我没能识别出金额。可以像这样发：午饭 36、昨天打车 42.8。"
        expense = await self.record(user_id, intent, raw_text=text)
        return expense, (
            f"已记账：{intent.occurred_on.isoformat()} {intent.category} "
            f"{intent.amount:.2f} 元，备注：{intent.note}"
        )

    async def record(
        self, user_id: UUID, intent: ExpenseRecordIntent, raw_text: str | None = None
    ) -> Expense:
        expense = Expense(
            user_id=user_id,
            occurred_on=intent.occurred_on,
            amount=intent.amount,
            currency=intent.currency,
            category=intent.category,
            merchant=intent.merchant,
            note_encrypted=self.encryptor.encrypt_text(intent.note),
            raw_text_encrypted=self.encryptor.encrypt_text(raw_text),
        )
        self.session.add(expense)
        await self.session.flush()
        return expense

    async def query_from_text(
        self, user_id: UUID, text: str, today: date | None = None
    ) -> tuple[ExpenseQueryIntent | None, str, dict]:
        intent = self.parser.parse_query(text, today=today)
        if intent is None:
            return None, "我没能识别出查询范围，可以问：这个月餐饮花了多少。", {}
        summary = await self.query(user_id, intent)
        category_text = f"{intent.category}" if intent.category else "全部分类"
        return (
            intent,
            f"{intent.start_on.isoformat()} 至 {intent.end_on.isoformat()}，"
            f"{category_text}合计 {summary['total']:.2f} 元，共 {summary['count']} 笔。",
            summary,
        )

    async def query(self, user_id: UUID, intent: ExpenseQueryIntent) -> dict:
        filters = [
            Expense.user_id == user_id,
            Expense.occurred_on >= intent.start_on,
            Expense.occurred_on <= intent.end_on,
        ]
        if intent.category:
            filters.append(Expense.category == intent.category)

        total = await self.session.scalar(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(and_(*filters))
        )
        count = await self.session.scalar(select(func.count(Expense.id)).where(and_(*filters)))
        by_category_rows = (
            await self.session.execute(
                select(Expense.category, func.coalesce(func.sum(Expense.amount), 0), func.count())
                .where(and_(*filters))
                .group_by(Expense.category)
                .order_by(func.sum(Expense.amount).desc())
            )
        ).all()
        return {
            "total": Decimal(total or 0),
            "count": int(count or 0),
            "by_category": [
                {"category": row[0], "total": float(row[1]), "count": row[2]}
                for row in by_category_rows
            ],
        }

    async def daily_summary(self, user_id: UUID, on_date: date | None = None) -> str:
        on_date = on_date or date.today()
        intent = ExpenseQueryIntent(start_on=on_date, end_on=on_date)
        summary = await self.query(user_id, intent)
        return f"今日花销 {summary['total']:.2f} 元，共 {summary['count']} 笔。"

    async def last_7_days_summary(self, user_id: UUID, today: date | None = None) -> str:
        today = today or date.today()
        intent = ExpenseQueryIntent(start_on=today - timedelta(days=6), end_on=today)
        summary = await self.query(user_id, intent)
        return f"最近 7 天花销 {summary['total']:.2f} 元，共 {summary['count']} 笔。"
