from __future__ import annotations

import hashlib
import math
import re


class HashingEmbedder:
    """Tiny no-cost embedding fallback.

    This keeps pgvector available without buying another embedding API. It is not as smart as a
    neural embedding model, but it is deterministic, private, and good enough for MVP retrieval.
    """

    dimension = 384

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = self._tokenize(text)
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _tokenize(self, text: str) -> list[str]:
        latin = re.findall(r"[a-zA-Z0-9_]+", text.lower())
        chinese_runs = re.findall(r"[\u4e00-\u9fff]+", text)
        chinese: list[str] = []
        for run in chinese_runs:
            chinese.extend(run)
            chinese.extend(run[index : index + 2] for index in range(max(len(run) - 1, 0)))
            chinese.extend(run[index : index + 3] for index in range(max(len(run) - 2, 0)))
        return latin + chinese


def token_overlap_score(query: str, content: str) -> float:
    query_tokens = set(HashingEmbedder()._tokenize(query))
    content_tokens = set(HashingEmbedder()._tokenize(content))
    if not query_tokens or not content_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / len(query_tokens | content_tokens)
