from __future__ import annotations

import re

from app.schemas import MemoryCandidate, MemoryType


EXPLICIT_MEMORY_PATTERNS = (
    re.compile(r"(?:请|帮我)?记住[:：]?\s*(?P<content>.+)"),
    re.compile(r"(?:请|帮我)?记一下[:：]?\s*(?P<content>.+)"),
    re.compile(r"(?:不要|别)忘(?:了|记)?[:：]?\s*(?P<content>.+)"),
    re.compile(r"(?:以后|之后)你(?:要|记得)?(?P<content>.+)"),
)

PREFERENCE_PATTERNS = (
    re.compile(r"我(?:喜欢|偏好|更喜欢|讨厌|不喜欢|受不了)(?P<content>.+)"),
    re.compile(r"我的(?:习惯|偏好|口味|风格|雷点|禁忌)是(?P<content>.+)"),
    re.compile(r"我(?:一般|通常|经常|总是|很少|不太)(?P<content>.+)"),
)

PROFILE_PATTERNS = (
    re.compile(r"我(?:叫|名叫|名字叫)(?P<content>.+)"),
    re.compile(r"(?:你以后叫我|以后叫我|叫我)(?P<content>.+)"),
    re.compile(r"我是(?P<content>.+)"),
    re.compile(r"我的(?:职业|工作|生日|城市|学校|公司|专业|年级|班级|住址|家乡)是(?P<content>.+)"),
)

RELATIONSHIP_PATTERNS = (
    re.compile(r"我的(?:朋友|同学|同事|家人|爸爸|妈妈|对象|女朋友|男朋友|老婆|老公)(?P<content>.+)"),
)

PROJECT_PATTERNS = (
    re.compile(r"我(?:正在|准备|打算|计划|想要|最近在)(?P<content>.+)"),
    re.compile(r"我的(?:项目|目标|计划|任务)(?:是|叫)?(?P<content>.+)"),
)

INSTRUCTION_PATTERNS = (
    re.compile(r"(?:以后|之后)(?:回复|回答|聊天|说话)(?P<content>.+)"),
    re.compile(r"(?:你要|你别|不要)(?P<content>.+)"),
)


class MemoryPolicy:
    def propose_from_user_text(self, text: str) -> list[MemoryCandidate]:
        text = text.strip()
        candidates: list[MemoryCandidate] = []

        for pattern in EXPLICIT_MEMORY_PATTERNS:
            match = pattern.search(text)
            if match:
                content = self._normalize(match.group("content"))
                if content:
                    candidates.append(
                        MemoryCandidate(
                            memory_type=self._infer_type(content),
                            content=content,
                            confidence=0.92,
                            source="explicit",
                        )
                    )

        for pattern in PREFERENCE_PATTERNS:
            match = pattern.search(text)
            if match:
                content = self._normalize(match.group(0))
                candidates.append(
                    MemoryCandidate(
                        memory_type="preference",
                        content=content,
                        confidence=0.82,
                        source="inferred",
                    )
                )

        for pattern in PROFILE_PATTERNS:
            match = pattern.search(text)
            if match:
                content = self._normalize(match.group(0))
                if 2 <= len(content) <= 80:
                    candidates.append(
                        MemoryCandidate(
                            memory_type="profile",
                            content=content,
                            confidence=0.75,
                            source="inferred",
                        )
                    )

        for pattern in RELATIONSHIP_PATTERNS:
            match = pattern.search(text)
            if match:
                content = self._normalize(match.group(0))
                if 4 <= len(content) <= 140:
                    candidates.append(
                        MemoryCandidate(
                            memory_type="relationship",
                            content=content,
                            confidence=0.78,
                            source="inferred",
                        )
                    )

        for pattern in PROJECT_PATTERNS:
            match = pattern.search(text)
            if match:
                content = self._normalize(match.group(0))
                if 4 <= len(content) <= 180:
                    candidates.append(
                        MemoryCandidate(
                            memory_type="project",
                            content=content,
                            confidence=0.76,
                            source="inferred",
                        )
                    )

        for pattern in INSTRUCTION_PATTERNS:
            match = pattern.search(text)
            if match:
                content = self._normalize(match.group(0))
                if 4 <= len(content) <= 180:
                    candidates.append(
                        MemoryCandidate(
                            memory_type="instruction",
                            content=content,
                            confidence=0.8,
                            source="inferred",
                        )
                    )

        return self._dedupe(candidates)

    def should_save(self, candidate: MemoryCandidate) -> bool:
        if candidate.confidence < 0.72:
            return False
        if len(candidate.content) < 2 or len(candidate.content) > 240:
            return False
        sensitive_words = ("身份证", "银行卡", "密码", "验证码", "私钥", "token", "api key")
        if any(word.lower() in candidate.content.lower() for word in sensitive_words):
            return candidate.source == "explicit" and candidate.confidence >= 0.9
        if self._looks_ephemeral_or_question(candidate.content):
            return candidate.source == "explicit"
        return True

    def _infer_type(self, content: str) -> MemoryType:
        if any(word in content for word in ("花销", "账单", "预算", "消费", "收入")):
            return "finance"
        if any(word in content for word in ("项目", "计划", "任务", "开发")):
            return "project"
        if any(word in content for word in ("以后", "回答", "称呼", "风格")):
            return "instruction"
        if any(word in content for word in ("喜欢", "讨厌", "偏好", "习惯")):
            return "preference"
        return "event"

    def _normalize(self, content: str) -> str:
        return re.sub(r"\s+", " ", content).strip(" ，,。.!！?？")

    def _looks_ephemeral_or_question(self, content: str) -> bool:
        if any(mark in content for mark in ("吗", "呢", "？", "?", "是不是", "为什么", "怎么")):
            return True
        ephemeral_words = ("刚才", "现在先", "等会", "一会儿", "临时", "随便")
        return any(word in content for word in ephemeral_words)

    def _dedupe(self, candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
        best_by_content: dict[str, MemoryCandidate] = {}
        for candidate in candidates:
            key = candidate.content
            existing = best_by_content.get(key)
            if existing is None or candidate.confidence > existing.confidence:
                best_by_content[key] = candidate
        return list(best_by_content.values())
