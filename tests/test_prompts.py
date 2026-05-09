from __future__ import annotations

from datetime import datetime

from app.brain.prompts import build_system_prompt


def test_persona_prompt_prefers_friend_tone_over_service_tone() -> None:
    prompt = build_system_prompt(["preference: 用户喜欢简洁回答"], datetime(2026, 5, 9, 20, 40))

    assert "像朋友聊天" in prompt
    assert "不要客服腔" in prompt
    assert "用户随手丢来的东西都要接住" in prompt
    assert "不要频繁说" in prompt
    assert "用户喜欢简洁回答" in prompt
