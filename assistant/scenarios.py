"""一天里的 10 个场景：正常发送，以及每一道护栏被触发的情况。"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .data import Faults, Sources
from .intents import Plan, route
from .pipeline import Assistant, Outbox, RunResult, load_config

DAY = datetime(2026, 10, 12)


@dataclass
class Scenario:
    title: str
    trigger: str
    guard: str
    plan: Plan | None
    result: RunResult | None
    note: str = ""


def at(h: int, m: int) -> datetime:
    return DAY.replace(hour=h, minute=m)


def run_all(audit_path: Path | None = None) -> tuple[list[Scenario], Assistant]:
    cfg = load_config()
    if audit_path and audit_path.exists():
        audit_path.unlink()
    bot = Assistant(cfg, Sources(seed=1), Outbox(), audit_path)
    out: list[Scenario] = []

    def ask(title, guard, text, when, faults=None, approved_by=None, outbox_fail=0):
        plan = route(text)
        if plan.unclear:
            out.append(Scenario(title, text, guard, plan, None, plan.unclear))
            return
        bot.sources = Sources(seed=when.hour * 60 + when.minute, faults=faults)
        bot.outbox.fail_times = outbox_fail
        out.append(Scenario(title, text, guard, plan, bot.run(plan.task, when, plan.regions, approved_by)))

    def schedule(title, guard, task, when, faults=None, approved_by=None, outbox_fail=0):
        bot.sources = Sources(seed=when.hour * 60 + when.minute, faults=faults)
        bot.outbox.fail_times = outbox_fail
        out.append(Scenario(title, f"定时任务 · {cfg['tasks'][task]['name']} · {when:%H:%M}", guard, None,
                            bot.run(task, when, approved_by=approved_by)))

    schedule("太早，不打扰", "时间护栏", "attainment", at(8, 5))
    ask("首次运行，先预览", "预览确认", "把今天华东华南各门店的达成进度做成卡片发到群里", at(9, 0))
    ask("负责人确认后发送", "固定收件人 · 禁言群跳过", "把今天华东华南各门店的达成进度做成卡片发到群里", at(9, 3),
        approved_by="区域负责人")
    schedule("调度器重复触发", "幂等锁", "attainment", at(9, 10))
    schedule("数据源偶发超时", "失败重试", "inventory", at(10, 0), faults=Faults(fail_calls={1}), approved_by="区域负责人")
    schedule("数据异常，拦下", "健康检查", "attainment", at(14, 0), faults=Faults(spike_store="深圳南山"))
    schedule("门店数据缺失，拦下", "健康检查", "attainment", at(14, 20), faults=Faults(drop_stores=["上海徐汇", "广州天河"]))
    schedule("发送通道限流", "发送重试 · message_id 留痕", "inventory", at(16, 0), outbox_fail=1)
    schedule("数据源持续失败", "重跑一次后放弃", "attainment", at(18, 0), faults=Faults(fail_calls={1, 2}))
    ask("越权请求", "收件人白名单", "把华东库存发到所有群", at(18, 30))
    return out, bot
