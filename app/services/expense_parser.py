from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

from app.schemas import ExpenseQueryIntent, ExpenseRecordIntent
from app.utils.dates import (
    month_range,
    parse_chinese_date,
    previous_month_range,
    previous_week_range,
    week_range,
)


EXPENSE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "餐饮": ("饭", "午餐", "晚餐", "早餐", "宵夜", "咖啡", "奶茶", "外卖", "餐饮", "吃"),
    "交通": ("打车", "地铁", "公交", "高铁", "火车", "机票", "出租", "交通", "油费", "停车"),
    "购物": ("购物", "淘宝", "京东", "拼多多", "买", "衣服", "鞋", "超市"),
    "居住": ("房租", "租金", "物业", "住宿", "酒店", "居住"),
    "水电通讯": ("水费", "电费", "燃气", "话费", "网费", "宽带", "通讯"),
    "娱乐": ("电影", "游戏", "演出", "娱乐", "会员", "门票"),
    "医疗": ("医院", "药", "体检", "医疗", "看病"),
    "学习": ("书", "课程", "学习", "学费", "培训"),
    "人情": ("红包", "礼物", "请客", "份子", "人情"),
    "收入": ("工资", "收入", "报销", "奖金", "退款"),
}

DEFAULT_CATEGORY = "其他"
AMOUNT_RE = re.compile(r"(?:¥|￥|RMB|rmb)?\s*(\d+(?:\.\d{1,2})?)\s*(?:元|块|块钱|RMB|rmb)?")
QUESTION_WORDS = ("多少", "几", "统计", "合计", "总共", "汇总", "账单", "花了", "支出")
SPEND_WORDS = ("花", "消费", "支出", "付款", "付了", "买", "买了", "用了", "转账", "记账", "记一笔")
INCOME_WORDS = ("工资", "收入", "奖金", "报销", "退款")
DELETE_WORDS = ("删除", "删掉", "撤销", "撤回", "记错", "取消这笔")
NON_RECORD_WORDS = (
    "预算",
    "提醒",
    "待办",
    "todo",
    "评估",
    "能不能",
    "可不可以",
    "想花",
    "准备花",
    "打算花",
    "计划花",
    "如果花",
)


class ExpenseParser:
    def parse_record(self, text: str, today: date | None = None) -> ExpenseRecordIntent | None:
        today = today or date.today()
        if self._looks_like_query(text) or self.looks_like_delete(text):
            return None
        if any(word.lower() in text.lower() for word in NON_RECORD_WORDS):
            return None

        matches = list(AMOUNT_RE.finditer(text))
        if not matches:
            return None

        amount_match = matches[-1]
        amount = Decimal(amount_match.group(1))
        if amount <= 0:
            return None

        occurred_on = parse_chinese_date(text, today=today) or today
        category = self.detect_category(text)
        note = self._clean_note(text, amount_match.group(0))
        if not self._has_record_signal(text, category, note):
            return None
        if not note:
            note = category

        return ExpenseRecordIntent(
            amount=amount,
            category=category,
            occurred_on=occurred_on,
            note=note,
            merchant=None,
        )

    def looks_like_delete(self, text: str) -> bool:
        return any(word in text for word in DELETE_WORDS) and any(
            word in text for word in ("账", "消费", "花销", "上一笔", "刚才", "这笔", "午饭", "打车")
        )

    def parse_query(self, text: str, today: date | None = None) -> ExpenseQueryIntent | None:
        today = today or date.today()
        if not self._looks_like_query(text):
            return None

        if "上个月" in text or "上月" in text:
            start_on, end_on = previous_month_range(today)
        elif "这个月" in text or "本月" in text or "月" in text:
            start_on, end_on = month_range(today)
        elif "上周" in text:
            start_on, end_on = previous_week_range(today)
        elif "这周" in text or "本周" in text:
            start_on, end_on = week_range(today)
        elif "昨天" in text:
            start_on = end_on = today - timedelta(days=1)
        elif "前天" in text:
            start_on = end_on = today - timedelta(days=2)
        elif "今天" in text:
            start_on = end_on = today
        else:
            start_on, end_on = month_range(today)

        category = self.detect_category(text)
        if category == DEFAULT_CATEGORY:
            category = None

        return ExpenseQueryIntent(start_on=start_on, end_on=end_on, category=category)

    def detect_category(self, text: str) -> str:
        for category, keywords in EXPENSE_CATEGORIES.items():
            if any(keyword in text for keyword in keywords):
                return category
        return DEFAULT_CATEGORY

    def _looks_like_query(self, text: str) -> bool:
        return any(word in text for word in QUESTION_WORDS) and (
            "多少" in text or "统计" in text or "合计" in text or "汇总" in text or "账单" in text
        )

    def _has_record_signal(self, text: str, category: str, note: str) -> bool:
        if category != DEFAULT_CATEGORY:
            return True
        if any(word in text for word in SPEND_WORDS + INCOME_WORDS):
            return len(note) >= 2
        return False

    def _clean_note(self, text: str, amount_text: str) -> str:
        note = text.replace(amount_text, " ")
        for token in ("今天", "今日", "昨天", "昨日", "前天", "花了", "消费", "支出"):
            note = note.replace(token, " ")
        note = re.sub(r"\d{4}[年/-]\d{1,2}[月/-]\d{1,2}日?", " ", note)
        note = re.sub(r"\d{1,2}月\d{1,2}日?", " ", note)
        note = re.sub(r"\s+", " ", note).strip(" ，,。.")
        return note
