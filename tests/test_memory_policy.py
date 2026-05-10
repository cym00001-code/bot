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


def test_memory_policy_captures_profile_relationship_and_projects() -> None:
    policy = MemoryPolicy()

    candidates = policy.propose_from_user_text("我叫陈一鸣，我的朋友小王在杭州，我最近在做微信机器人")
    by_type = {candidate.memory_type for candidate in candidates if policy.should_save(candidate)}

    assert "profile" in by_type
    assert "relationship" in by_type
    assert "project" in by_type


def test_memory_policy_rejects_inferred_questions() -> None:
    policy = MemoryPolicy()

    candidates = policy.propose_from_user_text("我喜欢什么风格吗？")

    assert all(not policy.should_save(candidate) for candidate in candidates)
