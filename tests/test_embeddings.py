from __future__ import annotations

from app.memory.embeddings import HashingEmbedder, token_overlap_score


def test_chinese_tokenizer_keeps_phrase_ngrams() -> None:
    tokens = HashingEmbedder()._tokenize("我喜欢简洁回答")

    assert "喜欢" in tokens
    assert "简洁" in tokens
    assert "回答" in tokens
    assert token_overlap_score("我喜欢什么", "我喜欢简洁回答") > 0
