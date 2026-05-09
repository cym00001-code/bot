from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from app.brain.deepseek import DeepSeekBrain
from app.core.config import Settings
from app.schemas import ChatContext


class EmptyTools:
    def list_for_model(self):
        return []


@pytest.mark.asyncio
async def test_deepseek_without_key_uses_local_fallback() -> None:
    settings = Settings(deepseek_api_key=None)
    context = ChatContext(
        user_id=uuid4(),
        user_text="你好",
        memories=[],
        recent_messages=[],
        now=datetime(2026, 5, 9, 12, 0),
    )

    reply = await DeepSeekBrain(settings).answer(context, EmptyTools())  # type: ignore[arg-type]

    assert "DeepSeek API Key" in reply or "已收到" in reply
