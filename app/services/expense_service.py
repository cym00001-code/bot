from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Encryptor
from app.db.models import Expense
from app.schemas import ExpenseQueryIntent, ExpenseRecordIntent
from app.services.expense_parser import AMOUNT_RE, ExpenseParser


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
            return None, "这句我没直接记账，怕记错。你可以像这样发：午饭 36、昨天打车 42.8。"
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

    async def delete_from_text(
        self, user_id: UUID, text: str, today: date | None = None
    ) -> tuple[int, str]:
        today = today or date.today()
        expense = await self._find_expense_to_delete(user_id, text, today)
        if expense is None:
            return 0, "没找到能确定删除的那笔。你可以说：删除上一笔，或 删除今天午饭36。"

        note = self.encryptor.decrypt_text(expense.note_encrypted) or expense.category
        await self.session.execute(delete(Expense).where(Expense.id == expense.id))
        return (
            1,
            f"删了：{expense.occurred_on.isoformat()} {expense.category} "
            f"{expense.amount:.2f} 元，{note}",
        )

    async def _find_expense_to_delete(
        self, user_id: UUID, text: str, today: date
    ) -> Expense | None:
        category = self.parser.detect_category(text)
        record_intent = self.parser.parse_record(text, today=today)
        amount_match = list(AMOUNT_RE.finditer(text))
        filters = [Expense.user_id == user_id]

        if "今天" in text or "今日" in text:
            filters.append(Expense.occurred_on == today)
        elif "昨天" in text or "昨日" in text:
            filters.append(Expense.occurred_on == today - timedelta(days=1))
        elif record_intent:
            filters.append(Expense.occurred_on == record_intent.occurred_on)

        if category != "其他":
            filters.append(Expense.category == category)
        if record_intent:
            filters.append(Expense.amount == record_intent.amount)
        elif amount_match:
            filters.append(Expense.amount == Decimal(amount_match[-1].group(1)))

        rows = (
            await self.session.scalars(
                select(Expense).where(and_(*filters)).order_by(Expense.created_at.desc()).limit(8)
            )
        ).all()
        if not rows:
            rows = (
                await self.session.scalars(
                    select(Expense)
                    .where(Expense.user_id == user_id)
                    .order_by(Expense.created_at.desc())
                    .limit(1)
                )
            ).all()
            if not any(word in text for word in ("上一笔", "刚才", "这笔", "记错", "撤销")):
                return None
        if len(rows) > 1 and not any(word in text for word in ("上一笔", "刚才", "这笔")):
            return None
        return rows[0] if rows else None

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
