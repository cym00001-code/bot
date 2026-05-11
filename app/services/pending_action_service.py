from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PendingAction


CONFIRM_WORDS = ("确认", "确定", "执行", "可以执行", "确认删除", "删吧", "是的", "对")
CANCEL_WORDS = ("取消", "算了", "不用了", "别删", "先不", "停止")


class PendingActionService:
    def __init__(self, session: AsyncSession, timezone: str) -> None:
        self.session = session
        self.timezone = timezone

    async def create_or_replace(
        self,
        user_id: UUID,
        tool_name: str,
        arguments: dict,
        risk_level: str,
        prompt: str,
        ttl_minutes: int = 10,
    ) -> PendingAction:
        now = datetime.now(ZoneInfo(self.timezone))
        await self.session.execute(
            update(PendingAction)
            .where(PendingAction.user_id == user_id, PendingAction.status == "pending")
            .values(status="superseded", completed_at=func.now())
        )
        action = PendingAction(
            user_id=user_id,
            tool_name=tool_name,
            arguments=arguments,
            risk_level=risk_level,
            prompt=prompt,
            expires_at=now + timedelta(minutes=ttl_minutes),
        )
        self.session.add(action)
        await self.session.flush()
        return action

    async def latest_pending(self, user_id: UUID) -> PendingAction | None:
        now = datetime.now(ZoneInfo(self.timezone))
        action = await self.session.scalar(
            select(PendingAction)
            .where(
                and_(
                    PendingAction.user_id == user_id,
                    PendingAction.status == "pending",
                    PendingAction.expires_at > now,
                )
            )
            .order_by(PendingAction.created_at.desc())
            .limit(1)
        )
        if action:
            return action
        await self.expire_old(user_id)
        return None

    async def expire_old(self, user_id: UUID) -> None:
        now = datetime.now(ZoneInfo(self.timezone))
        await self.session.execute(
            update(PendingAction)
            .where(
                PendingAction.user_id == user_id,
                PendingAction.status == "pending",
                PendingAction.expires_at <= now,
            )
            .values(status="expired", completed_at=func.now())
        )

    async def mark_done(self, action: PendingAction) -> None:
        await self.session.execute(
            update(PendingAction)
            .where(PendingAction.id == action.id)
            .values(status="done", completed_at=func.now())
        )

    async def cancel_latest(self, user_id: UUID) -> bool:
        action = await self.latest_pending(user_id)
        if action is None:
            return False
        await self.session.execute(
            update(PendingAction)
            .where(PendingAction.id == action.id)
            .values(status="cancelled", completed_at=func.now())
        )
        return True

    def looks_like_confirm(self, text: str) -> bool:
        normalized = text.strip().lower()
        return normalized in CONFIRM_WORDS or normalized in {"yes", "y", "ok", "okay"}

    def looks_like_cancel(self, text: str) -> bool:
        normalized = text.strip().lower()
        return normalized in CANCEL_WORDS or normalized in {"no", "n"}
