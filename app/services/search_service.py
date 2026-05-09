from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        if not self.settings.search_enabled:
            return {
                "degraded": True,
                "summary": "搜索功能当前关闭。我可以先根据已有知识和记忆回答，但可能不是最新。",
                "results": [],
            }

        try:
            async with httpx.AsyncClient(timeout=self.settings.search_timeout_seconds) as client:
                response = await client.get(
                    f"{self.settings.searxng_base_url}/search",
                    params={"q": query, "format": "json", "language": "zh-CN"},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # pragma: no cover - exercised by integration environments
            logger.warning("search degraded: %s", exc)
            return {
                "degraded": True,
                "summary": "联网搜索暂时不可用。我可以先回答，但涉及新闻、价格、政策时请再核对。",
                "results": [],
            }

        results = []
        for item in payload.get("results", [])[:limit]:
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                }
            )
        return {
            "degraded": False,
            "summary": f"找到 {len(results)} 条搜索结果。",
            "results": results,
        }
