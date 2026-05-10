from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Encryptor
from app.db.models import Budget
from app.schemas import BudgetIntent, ExpenseQueryIntent, SpendEvaluationIntent
from app.services.expense_parser import AMOUNT_RE, ExpenseParser
from app.services.expense_service import ExpenseService
from app.utils.dates import month_range


class BudgetService:
    def __init__(
        self,
        session: AsyncSession,
        encryptor: Encryptor,
        expense_service: ExpenseService | None = None,
        parser: ExpenseParser | None = None,
    ) -> None:
        self.session = session
        self.encryptor = encryptor
        self.parser = parser or ExpenseParser()
        self.expense_service = expense_service or ExpenseService(session, encryptor, self.parser)

    async def set_budget_from_text(
        self, user_id: UUID, text: str, today: date | None = None
    ) -> tuple[Budget | None, str]:
        intent = self.parse_budget(text, today=today)
        if intent is None:
            return None, "预算我没读准。可以说：这个月预算3000，或 本月餐饮预算800。"

        existing = await self.session.scalar(
            select(Budget).where(
                and_(
                    Budget.user_id == user_id,
                    Budget.month == intent.month,
                    Budget.category.is_(None)
                    if intent.category is None
                    else Budget.category == intent.category,
                )
            )
        )
        if existing:
            existing.amount = intent.amount
            existing.note_encrypted = self.encryptor.encrypt_text(intent.note)
            budget = existing
        else:
            budget = Budget(
                user_id=user_id,
                month=intent.month,
                amount=intent.amount,
                category=intent.category,
                note_encrypted=self.encryptor.encrypt_text(intent.note),
            )
            self.session.add(budget)
        await self.session.flush()
        label = f"{intent.category}" if intent.category else "总"
        return budget, f"{intent.month:%Y-%m} {label}预算设为 {intent.amount:.2f} 元。"

    async def evaluate_from_text(
        self, user_id: UUID, text: str, today: date | None = None
    ) -> tuple[SpendEvaluationIntent | None, str]:
        today = today or date.today()
        intent = self.parse_spend_evaluation(text, today=today)
        if intent is None:
            return None, "这笔我没读准。你可以说：想花 200 买鞋，帮我评估。"

        month_start, month_end = month_range(today)
        budget = await self._find_best_budget(user_id, month_start, intent.category)
        if budget is None:
            return intent, "你还没设这个月预算。先说“这个月预算3000”，我再帮你判断这笔值不值得花。"

        category = budget.category or None
        summary = await self.expense_service.query(
            user_id,
            ExpenseQueryIntent(start_on=month_start, end_on=month_end, category=category),
        )
        spent = Decimal(summary["total"])
        remaining = Decimal(budget.amount) - spent
        after = remaining - intent.amount
        label = budget.category or "总"
        if after >= 0:
            verdict = "可以花，但别顺手加码。"
        elif after >= Decimal("-100"):
            verdict = "会轻微超预算，想清楚再花。"
        else:
            verdict = "不太建议，超得有点明显。"
        return (
            intent,
            f"{label}预算 {Decimal(budget.amount):.2f}，已花 {spent:.2f}，"
            f"剩 {remaining:.2f}。这笔 {intent.amount:.2f} 花完后剩 {after:.2f}。{verdict}",
        )

    async def summary_from_text(
        self, user_id: UUID, text: str, today: date | None = None
    ) -> str | None:
        if "预算" not in text or not any(word in text for word in ("剩", "还有", "多少", "情况")):
            return None
        today = today or date.today()
        month_start, month_end = month_range(today)
        budgets = (
            await self.session.scalars(
                select(Budget).where(Budget.user_id == user_id, Budget.month == month_start)
            )
        ).all()
        if not budgets:
            return "这个月还没设预算。你可以说：这个月预算3000。"
        lines: list[str] = []
        for budget in budgets:
            summary = await self.expense_service.query(
                user_id,
                ExpenseQueryIntent(
                    start_on=month_start, end_on=month_end, category=budget.category
                ),
            )
            spent = Decimal(summary["total"])
            remaining = Decimal(budget.amount) - spent
            label = budget.category or "总"
            lines.append(f"{label}预算 {Decimal(budget.amount):.2f}，已花 {spent:.2f}，剩 {remaining:.2f}")
        return "\n".join(lines)

    def parse_budget(self, text: str, today: date | None = None) -> BudgetIntent | None:
        today = today or date.today()
        if "预算" not in text or any(word in text for word in ("还剩", "剩多少", "够不够", "评估")):
            return None
        matches = list(AMOUNT_RE.finditer(text))
        if not matches:
            return None
        amount = Decimal(matches[-1].group(1))
        if amount <= 0:
            return None
        month = month_range(today)[0]
        category = self.parser.detect_category(text)
        return BudgetIntent(
            month=month,
            amount=amount,
            category=None if category == "其他" else category,
            note=text,
        )

    def parse_spend_evaluation(
        self, text: str, today: date | None = None
    ) -> SpendEvaluationIntent | None:
        today = today or date.today()
        if not any(word in text for word in ("想花", "准备花", "打算花", "能不能买", "可不可以买", "评估")):
            return None
        matches = list(AMOUNT_RE.finditer(text))
        if not matches:
            return None
        amount = Decimal(matches[-1].group(1))
        note = re.sub(r"\s+", " ", text.replace(matches[-1].group(0), " ")).strip(" ，,。.")
        category = self.parser.detect_category(text)
        return SpendEvaluationIntent(
            amount=amount,
            category=None if category == "其他" else category,
            note=note,
            occurred_on=today,
        )

    async def _find_best_budget(
        self, user_id: UUID, month: date, category: str | None
    ) -> Budget | None:
        if category:
            category_budget = await self.session.scalar(
                select(Budget).where(
                    Budget.user_id == user_id,
                    Budget.month == month,
                    Budget.category == category,
                )
            )
            if category_budget:
                return category_budget
        return await self.session.scalar(
            select(Budget).where(
                Budget.user_id == user_id,
                Budget.month == month,
                Budget.category.is_(None),
            )
        )
