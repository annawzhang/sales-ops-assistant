"""模拟数据源：订单系统、库存表格、看板。可注入故障用于演示。"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

REGIONS = {
    "华东": ["上海徐汇", "上海浦东", "杭州西湖", "杭州滨江", "南京新街口", "苏州园区", "宁波鄞州", "合肥政务"],
    "华南": ["广州天河", "广州番禺", "深圳南山", "深圳福田", "佛山禅城", "东莞南城", "厦门思明"],
}
MODELS = ["A8", "M7", "A6"]


class SourceError(Exception):
    """数据源偶发失败（超时、限流），可以重试。"""


@dataclass
class Faults:
    """注入的故障：按调用次数生效，便于复现。"""
    fail_calls: set[int] = field(default_factory=set)
    drop_stores: list[str] = field(default_factory=list)
    spike_store: str | None = None
    stale_hours: float = 0.0


class Sources:
    def __init__(self, seed: int = 1, faults: Faults | None = None):
        self.rng = random.Random(seed)
        self.faults = faults or Faults()
        self.calls = 0

    def fetch_orders(self, now: datetime) -> dict:
        self.calls += 1
        if self.calls in self.faults.fail_calls:
            raise SourceError("订单系统接口超时")
        rows = []
        for region, stores in REGIONS.items():
            for s in stores:
                if s in self.faults.drop_stores:
                    continue
                target = self.rng.randint(40, 90)
                done = int(target * self.rng.uniform(0.45, 1.25))
                if s == self.faults.spike_store:
                    done = target * 9
                rows.append({"region": region, "store": s, "target": target, "orders": done,
                             "test_drives": int(done * self.rng.uniform(2.2, 3.4))})
        return {"rows": rows, "updated_at": now - timedelta(hours=self.faults.stale_hours, minutes=12),
                "expected_stores": sum(len(v) for v in REGIONS.values())}

    def fetch_inventory(self, now: datetime) -> dict:
        self.calls += 1
        if self.calls in self.faults.fail_calls:
            raise SourceError("库存表格读取失败")
        rows = [{"region": r, "store": s, "model": m, "units": self.rng.randint(0, 14)}
                for r, stores in REGIONS.items() for s in stores for m in MODELS]
        return {"rows": rows, "updated_at": now - timedelta(minutes=30), "expected_stores": sum(len(v) for v in REGIONS.values())}
