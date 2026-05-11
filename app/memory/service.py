from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Encryptor, stable_hash
from app.db.models import Memory
from app.memory.embeddings import HashingEmbedder, token_overlap_score
from app.memory.policy import MemoryPolicy
from app.schemas import MemoryCandidate, RetrievedMemory


class MemoryService:
    def __init__(
        self,
        session: AsyncSession,
        encryptor: Encryptor,
        policy: MemoryPolicy | None = None,
        embedder: HashingEmbedder | None = None,
    ) -> None:
        self.session = session
        self.encryptor = encryptor
        self.policy = policy or MemoryPolicy()
        self.embedder = embedder or HashingEmbedder()

    async def remember_from_text(self, user_id: UUID, text: str) -> list[RetrievedMemory]:
        saved: list[RetrievedMemory] = []
        for candidate in self.policy.propose_from_user_text(text):
            if not self.policy.should_save(candidate):
                continue
            saved_memory = await self.save_candidate(user_id, candidate)
            if saved_memory:
                saved.append(saved_memory)
        return saved

    async def save_candidate(
        self, user_id: UUID, candidate: MemoryCandidate
    ) -> RetrievedMemory | None:
        content_hash = stable_hash(f"{candidate.memory_type}:{candidate.content}")
        existing = await self.session.scalar(
            select(Memory).where(
                and_(
                    Memory.user_id == user_id,
                    Memory.content_hash == content_hash,
                    Memory.deleted_at.is_(None),
                )
            )
        )
        if existing:
            return None

        memory = Memory(
            user_id=user_id,
            memory_type=candidate.memory_type,
            content_encrypted=self.encryptor.encrypt_text(candidate.content) or "",
            content_hash=content_hash,
            confidence=candidate.confidence,
            source=candidate.source,
            embedding=self.embedder.embed(candidate.content),
        )
        self.session.add(memory)
        await self.session.flush()
        return RetrievedMemory(
            id=memory.id,
            memory_type=memory.memory_type,
            content=candidate.content,
            confidence=memory.confidence,
        )

    async def retrieve(self, user_id: UUID, query: str, limit: int = 8) -> list[RetrievedMemory]:
        rows = (
            await self.session.scalars(
                select(Memory)
                .where(Memory.user_id == user_id, Memory.deleted_at.is_(None))
                .order_by(Memory.updated_at.desc())
                .limit(max(limit * 8, 40))
            )
        ).all()

        scored: list[tuple[float, Memory, str]] = []
        for index, row in enumerate(rows):
            content = self.encryptor.decrypt_text(row.content_encrypted) or ""
            recency = max(0.0, 0.12 - index * 0.004)
            score = (
                token_overlap_score(query, content) * 2.2
                + self._type_query_boost(query, row.memory_type)
                + row.confidence * 0.12
                + recency
            )
            scored.append((score, row, content))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            RetrievedMemory(
                id=row.id,
                memory_type=row.memory_type,
                content=content,
                confidence=row.confidence,
            )
            for _, row, content in scored[:limit]
        ]

    def _type_query_boost(self, query: str, memory_type: str) -> float:
        if any(word in query for word in ("喜欢", "偏好", "习惯", "口味", "风格")):
            return 0.35 if memory_type in {"preference", "instruction"} else 0.0
        if any(word in query for word in ("我是谁", "我的名字", "叫我", "职业", "生日", "城市")):
            return 0.35 if memory_type == "profile" else 0.0
        if any(word in query for word in ("朋友", "同学", "家人", "对象", "关系")):
            return 0.35 if memory_type == "relationship" else 0.0
        if any(word in query for word in ("项目", "计划", "目标", "任务", "最近在")):
            return 0.35 if memory_type == "project" else 0.0
        if any(word in query for word in ("记得", "记住", "记忆", "你知道我什么")):
            return 0.18
        return 0.0

    async def forget_matching(self, user_id: UUID, keyword: str) -> int:
        rows = (
            await self.session.scalars(
                select(Memory).where(Memory.user_id == user_id, Memory.deleted_at.is_(None))
            )
        ).all()
        matched_ids = [
            row.id
            for row in rows
            if keyword in (self.encryptor.decrypt_text(row.content_encrypted) or "")
        ]
        if not matched_ids:
            return 0
        await self.session.execute(
            update(Memory).where(Memory.id.in_(matched_ids)).values(deleted_at=func.now())
        )
        return len(matched_ids)

    async def list_recent(self, user_id: UUID, limit: int = 10) -> list[RetrievedMemory]:
        rows = (
            await self.session.scalars(
                select(Memory)
                .where(Memory.user_id == user_id, Memory.deleted_at.is_(None))
                .order_by(Memory.updated_at.desc())
                .limit(max(1, min(limit, 30)))
            )
        ).all()
        memories: list[RetrievedMemory] = []
        for row in rows:
            memories.append(
                RetrievedMemory(
                    id=row.id,
                    memory_type=row.memory_type,
                    content=self.encryptor.decrypt_text(row.content_encrypted) or "",
                    confidence=row.confidence,
                )
            )
        return memories

    async def forget_recent_index(self, user_id: UUID, index: int, limit: int = 10) -> int:
        if index < 1:
            return 0
        memories = await self.list_recent(user_id, limit=limit)
        if index > len(memories):
            return 0
        return await self.forget_by_id(user_id, memories[index - 1].id)

    async def forget_by_id(self, user_id: UUID, memory_id: UUID) -> int:
        result = await self.session.execute(
            update(Memory)
            .where(
                Memory.id == memory_id,
                Memory.user_id == user_id,
                Memory.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        return int(result.rowcount or 0)

    async def organize_summary(self, user_id: UUID, limit: int = 20) -> str:
        memories = await self.list_recent(user_id, limit=limit)
        if not memories:
            return "现在还没记下太多。"
        labels = {
            "profile": "个人资料",
            "preference": "偏好",
            "relationship": "关系",
            "event": "事件",
            "finance": "财务",
            "project": "项目",
            "instruction": "互动偏好",
        }
        grouped: dict[str, list[str]] = {}
        for memory in memories:
            grouped.setdefault(memory.memory_type, []).append(memory.content)
        lines: list[str] = []
        for memory_type, contents in grouped.items():
            label = labels.get(memory_type, memory_type)
            lines.append(f"{label}：")
            lines.extend(f"- {content}" for content in contents[:5])
        return "我整理了一下最近的记忆：\n" + "\n".join(lines)
