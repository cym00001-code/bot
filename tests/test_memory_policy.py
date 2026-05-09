from __future__ import annotations

from app.memory.policy import MemoryPolicy


def test_explicit_memory_is_high_confidence() -> None:
    policy = MemoryPolicy()

    candidates = policy.propose_from_user_text("记住我喜欢简洁回答")

    assert len(candidates) == 1
    assert candidates[0].memory_type in {"preference", "instruction"}
    assert candidates[0].confidence >= 0.9
    assert policy.should_save(candidates[0])


def test_sensitive_inferred_memory_is_rejected() -> None:
    policy = MemoryPolicy()

    candidate = policy.propose_from_user_text("我喜欢把密码写在备忘录里")[0]

    assert not policy.should_save(candidate)
