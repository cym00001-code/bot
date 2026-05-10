from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.brain.prompts import build_system_prompt
from app.core.config import Settings
from app.schemas import ChatContext
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class DeepSeekBrain:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def answer(self, context: ChatContext, tools: ToolRegistry) -> str:
        if not self.settings.has_deepseek_key:
            return self._local_fallback(context)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(context.memories, context.now)}
        ]
        messages.extend(context.recent_messages[-12:])
        messages.append({"role": "user", "content": context.user_text})

        model = self._choose_model(context.user_text, has_tools=True)
        tool_names = self._tool_names_for_text(context.user_text)
        tool_specs = tools.list_for_model(tool_names) if tool_names else []

        try:
            first = await self._chat_completion(messages, model=model, tools=tool_specs)
            choice = first["choices"][0]["message"]
            tool_calls = choice.get("tool_calls") or []
            if not tool_calls:
                return choice.get("content") or "我在。"

            messages.append(choice)
            for call in tool_calls:
                name = call.get("function", {}).get("name", "")
                args = self._parse_tool_arguments(call.get("function", {}).get("arguments"))
                result = await tools.execute(name, user_id=context.user_id, arguments=args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": result.model_dump_json(),
                    }
                )

            final = await self._chat_completion(messages, model=self.settings.deepseek_chat_model)
            return final["choices"][0]["message"].get("content") or "已处理。"
        except Exception as exc:
            logger.exception("deepseek request failed: %s", exc)
            return "我这边调用大脑时出了一点问题，但消息已经收到。你可以稍后再试。"

    async def _chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        api_key = self.settings.deepseek_api_key.get_secret_value()  # type: ignore[union-attr]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.4,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=self.settings.deepseek_timeout_seconds) as client:
            response = await client.post(
                f"{self.settings.deepseek_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    def _choose_model(self, text: str, has_tools: bool) -> str:
        if has_tools:
            return self.settings.deepseek_chat_model
        complex_markers = ("深入", "推理", "分析", "规划", "复杂", "为什么", "TOT")
        if any(marker in text for marker in complex_markers):
            return self.settings.deepseek_reasoner_model
        return self.settings.deepseek_chat_model

    def _tool_names_for_text(self, text: str) -> set[str]:
        names: set[str] = set()
        if any(word in text for word in ("搜索", "搜一下", "查一下", "最新", "新闻", "价格", "实时")):
            names.add("web_search")
        if any(word in text for word in ("删除记忆", "忘掉", "别记了", "清除记忆")):
            names.add("memory_forget")
        if any(word in text for word in ("删除账", "删掉账", "撤销", "记错")):
            names.add("expense_delete")
        if any(word in text for word in ("花销", "账单", "花了多少", "消费统计", "记账")):
            names.update({"expense_record", "expense_query", "expense_delete"})
        if "预算" in text or any(word in text for word in ("想花", "准备花", "打算花", "评估")):
            names.update({"budget_set", "budget_evaluate"})
        if any(word in text for word in ("提醒", "待办", "todo", "完成")):
            names.update({"reminder_create", "reminder_list", "reminder_complete"})
        return names

    def _parse_tool_arguments(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _local_fallback(self, context: ChatContext) -> str:
        lowered = context.user_text.lower()
        if "deepseek" in lowered or "api" in lowered:
            return "我已经运行起来了；填入 DeepSeek 和企业微信配置后，就可以开始真实对话。"
        return "我已收到。当前还没配置 DeepSeek API Key，所以先用本地规则处理记账、提醒和记忆。"
