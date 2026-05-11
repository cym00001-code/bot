from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from app.core.security import Encryptor, stable_hash
from app.db.models import Memory
from app.memory.service import MemoryService


class ScalarResult:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class ExecuteResult:
    rowcount = 1


class FakeSession:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.executed = []

    async def scalars(self, statement):
        return ScalarResult(self.rows)

    async def execute(self, statement):
        self.executed.append(statement)
        return ExecuteResult()


def make_memory(encryptor: Encryptor, memory_type: str, content: str) -> Memory:
    return Memory(
        id=uuid4(),
        user_id=uuid4(),
        memory_type=memory_type,
        content_encrypted=encryptor.encrypt_text(content) or "",
        content_hash=stable_hash(f"{memory_type}:{content}"),
        confidence=0.9,
        source="test",
        created_at=datetime(2026, 5, 10, 12, 0),
        updated_at=datetime(2026, 5, 10, 12, 0),
    )


@pytest.mark.asyncio
async def test_memory_organize_groups_by_type() -> None:
    encryptor = Encryptor("test")
    rows = [
        make_memory(encryptor, "preference", "我喜欢简洁回答"),
        make_memory(encryptor, "project", "我最近在做微信机器人"),
    ]
    service = MemoryService(FakeSession(rows), encryptor)  # type: ignore[arg-type]

    summary = await service.organize_summary(uuid4())

    assert "偏好" in summary
    assert "项目" in summary
    assert "我喜欢简洁回答" in summary


@pytest.mark.asyncio
async def test_forget_by_id_soft_deletes_memory() -> None:
    encryptor = Encryptor("test")
    memory = make_memory(encryptor, "preference", "我喜欢简洁回答")
    session = FakeSession([memory])
    service = MemoryService(session, encryptor)  # type: ignore[arg-type]

    deleted = await service.forget_by_id(uuid4(), memory.id)

    assert deleted == 1
    assert session.executed
