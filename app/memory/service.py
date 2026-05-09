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
                .limit(max(limit * 4, 16))
            )
        ).all()

        scored: list[tuple[float, Memory, str]] = []
        for row in rows:
            content = self.encryptor.decrypt_text(row.content_encrypted) or ""
            score = token_overlap_score(query, content) + row.confidence * 0.05
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
