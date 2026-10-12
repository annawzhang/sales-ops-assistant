"""把一句自然语言需求拆成结构化任务。规则路由，结果可解释、可复现。"""

import re
from dataclasses import dataclass, field

INTENTS = [
    ("attainment", ["达成", "完成率", "进度", "目标"]),
    ("inventory", ["库存", "现车", "车源"]),
    ("leaderboard", ["龙虎榜", "排名", "排行", "top"]),
    ("policy", ["政策", "提醒", "通知"]),
]
REGION_WORDS = {"华东": ["华东", "上海", "杭州", "南京"], "华南": ["华南", "广州", "深圳"]}
SEND_WORDS = ["发", "推送", "播报", "同步到", "群"]
CHART_WORDS = ["图", "截图", "卡片", "看板"]


@dataclass
class Plan:
    text: str
    task: str | None
    regions: list[str]
    send: bool
    want_chart: bool
    steps: list[str] = field(default_factory=list)
    unclear: str | None = None


def route(text: str) -> Plan:
    low = text.lower()
    scores = {key: sum(w in low for w in words) for key, words in INTENTS}
    best = max(scores, key=scores.get)
    task = best if scores[best] > 0 else None
    regions = [r for r, words in REGION_WORDS.items() if any(w in text for w in words)] or ["华东", "华南"]
    send = any(w in text for w in SEND_WORDS)
    chart = any(w in text for w in CHART_WORDS)
    plan = Plan(text, task, regions, send, chart)
    if task is None:
        plan.unclear = "没有识别出要查的指标，请说明是达成、库存、龙虎榜还是政策提醒"
        return plan
    plan.steps = ["refresh", "compute", "render"] + (["health_check", "preview", "send"] if send else ["health_check", "preview"])
    if re.search(r"(所有|全部)群", text):
        plan.unclear = "不支持发到「所有群」，只能发到任务配置里的固定收件人"
    return plan
