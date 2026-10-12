"""确定性流水线：刷新 → 计算 → 渲染 → 健康检查 → 预览确认 → 发送留痕。

指标全部由程序计算，不交给模型生成；每一步的状态写入审计日志，发送结果带 message_id。
"""

import hashlib
import json
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

from .data import SourceError, Sources

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path = ROOT / "config" / "assistant.toml") -> dict:
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    groups = {g["id"] for g in cfg["groups"]}
    for key, task in cfg["tasks"].items():
        unknown = [r for r in task["recipients"] if r not in groups]
        if unknown:
            raise ValueError(f"任务 {key} 的收件人不存在：{unknown}")
    return cfg


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


class Outbox:
    """模拟消息通道。真实环境替换成 IM 机器人接口即可。"""

    def __init__(self, fail_times: int = 0):
        self.sent: list[dict] = []
        self.fail_times = fail_times

    def send(self, group: dict, content: str, run_id: str) -> str:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise SourceError(f"发送到「{group['name']}」失败：通道限流")
        message_id = "om_" + hashlib.sha1(f"{run_id}:{group['id']}".encode()).hexdigest()[:12]
        self.sent.append({"group": group["id"], "run_id": run_id, "message_id": message_id, "content": content})
        return message_id


@dataclass
class RunResult:
    run_id: str
    task: str
    status: str            # sent / skipped / blocked / pending_approval / failed
    reason: str = ""
    attempts: int = 0
    events: list[dict] = field(default_factory=list)
    preview: str = ""
    delivered: list[dict] = field(default_factory=list)


class Assistant:
    def __init__(self, cfg: dict, sources: Sources, outbox: Outbox, audit_path: Path | None = None):
        self.cfg = cfg
        self.sources = sources
        self.outbox = outbox
        self.audit_path = audit_path
        self.locks: set[str] = set()
        self.history: set[str] = set()
        self.audit: list[dict] = []
        self.groups = {g["id"]: g for g in cfg["groups"]}

    # ---------- 护栏 ----------
    def _lock_key(self, task: str, now: datetime) -> str:
        slot = "AM" if now.hour < 13 else "PM"
        return f"{task}:{now:%Y-%m-%d}:{slot}"

    def _in_window(self, now: datetime) -> bool:
        w = self.cfg["send_window"]
        return _hm(w["start"]) <= now.time() <= _hm(w["end"])

    def _recipients(self, task: str, regions: list[str], log) -> list[dict]:
        out = []
        for gid in self.cfg["tasks"][task]["recipients"]:
            g = self.groups[gid]
            if g.get("sensitive"):
                log("recipients", "skip", f"「{g['name']}」含外部成员，禁止发送")
                continue
            if g.get("muted"):
                log("recipients", "skip", f"「{g['name']}」是禁言群，自动跳过")
                continue
            if g["region"] != "全部" and g["region"] not in regions:
                continue
            out.append(g)
        return out

    def _health(self, payload: dict, now: datetime) -> list[str]:
        h = self.cfg["health"]
        issues = []
        coverage = len({r["store"] for r in payload["rows"]}) / payload["expected_stores"]
        if coverage < h["min_store_coverage"]:
            issues.append(f"门店覆盖率 {coverage:.0%}，低于 {h['min_store_coverage']:.0%}")
        age = (now - payload["updated_at"]).total_seconds() / 3600
        if age > h["max_staleness_hours"]:
            issues.append(f"数据已 {age:.1f} 小时未更新")
        for r in payload["rows"]:
            if "target" in r and r["target"] and r["orders"] / r["target"] > h["max_attainment"]:
                issues.append(f"{r['store']} 达成率 {r['orders'] / r['target']:.0%}，疑似重复计数")
        return issues

    # ---------- 计算与渲染 ----------
    @staticmethod
    def compute(task: str, payload: dict, regions: list[str]) -> list[dict]:
        rows = [r for r in payload["rows"] if r["region"] in regions]
        if task == "inventory":
            stores = {}
            for r in rows:
                stores.setdefault((r["region"], r["store"]), 0)
                stores[(r["region"], r["store"])] += r["units"]
            return sorted(({"region": k[0], "store": k[1], "value": v} for k, v in stores.items()), key=lambda x: x["value"])
        out = [{"region": r["region"], "store": r["store"], "value": r["orders"] / r["target"],
                "orders": r["orders"], "target": r["target"]} for r in rows]
        return sorted(out, key=lambda x: -x["value"])

    @staticmethod
    def render(task_name: str, metrics: list[dict], task: str, now: datetime) -> str:
        if task == "inventory":
            low = [m for m in metrics if m["value"] <= 12][:5]
            lines = [f"【{task_name}】{now:%m-%d %H:%M}", f"库存偏低门店 {len(low)} 家："]
            lines += [f"· {m['store']}：{m['value']} 台" for m in low]
            return "\n".join(lines)
        total_o = sum(m["orders"] for m in metrics)
        total_t = sum(m["target"] for m in metrics)
        top = metrics[:3]
        bottom = [m for m in metrics if m["value"] < 0.7][-3:]
        lines = [f"【{task_name}】{now:%m-%d %H:%M}", f"整体达成 {total_o}/{total_t}（{total_o / total_t:.0%}）",
                 "TOP3：" + "、".join(f"{m['store']} {m['value']:.0%}" for m in top)]
        if bottom:
            lines.append("需关注：" + "、".join(f"{m['store']} {m['value']:.0%}" for m in bottom))
        return "\n".join(lines)

    # ---------- 主流程 ----------
    def run(self, task: str, now: datetime, regions: list[str] | None = None,
            approved_by: str | None = None) -> RunResult:
        regions = regions or ["华东", "华南"]
        run_id = f"{task}-{now:%Y%m%d%H%M%S}"
        result = RunResult(run_id, task, "failed")

        def log(step, status, detail=""):
            e = {"run_id": run_id, "time": now.isoformat(timespec="minutes"), "task": task,
                 "step": step, "status": status, "detail": detail}
            result.events.append(e)
            self.audit.append(e)
            if self.audit_path:
                with open(self.audit_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")

        def finish(status, reason=""):
            result.status, result.reason = status, reason
            log("finish", status, reason)
            return result

        key = self._lock_key(task, now)
        if key in self.locks:
            log("lock", "skip", f"同一时段已执行过（{key}）")
            return finish("skipped", "幂等锁：本时段已发送，不重复执行")
        if not self._in_window(now):
            w = self.cfg["send_window"]
            log("window", "stop", f"{now:%H:%M} 不在 {w['start']}–{w['end']} 发送窗口内")
            return finish("blocked", "时间护栏：非工作时段不打扰")

        fetch = self.sources.fetch_inventory if task == "inventory" else self.sources.fetch_orders
        max_attempts = self.cfg["retry"]["max_attempts"]
        for attempt in range(1, max_attempts + 1):
            result.attempts = attempt
            try:
                payload = fetch(now)
                log("refresh", "ok", f"第 {attempt} 次刷新，{len(payload['rows'])} 行")
                break
            except SourceError as e:
                log("refresh", "error", f"第 {attempt} 次：{e}")
                if attempt == max_attempts:
                    return finish("failed", f"重试 {max_attempts - 1} 次后仍失败，已通知负责人，未发送任何内容")
                log("retry", "wait", f"等待 {self.cfg['retry']['wait_seconds']} 秒后完整重跑")

        issues = self._health(payload, now)
        if issues:
            log("health_check", "fail", "；".join(issues))
            return finish("blocked", "健康检查未通过：" + issues[0])
        log("health_check", "ok", "字段完整、数值合理、数据新鲜")

        task_name = self.cfg["tasks"][task]["name"]
        metrics = self.compute(task, payload, regions)
        result.preview = self.render(task_name, metrics, task, now)
        log("render", "ok", f"{len(metrics)} 家门店")

        recipients = self._recipients(task, regions, log)
        if not recipients:
            return finish("blocked", "没有可发送的群")
        need_approval = ((self.cfg["approval"]["first_run"] and task not in self.history)
                         or len(recipients) > self.cfg["approval"]["max_groups_without_approval"])
        if need_approval and not approved_by:
            log("preview", "pending", f"待负责人确认，拟发 {len(recipients)} 个群：" + "、".join(g["name"] for g in recipients))
            return finish("pending_approval", "预览已生成，等待负责人确认")
        log("preview", "approved" if approved_by else "auto", f"确认人：{approved_by}" if approved_by else "常规任务，免确认")

        self.locks.add(key)
        for g in recipients:
            for attempt in range(1, max_attempts + 1):
                try:
                    mid = self.outbox.send(g, result.preview, run_id)
                    result.delivered.append({"group": g["name"], "message_id": mid})
                    log("send", "ok", f"{g['name']} · {mid}")
                    break
                except SourceError as e:
                    log("send", "error", str(e))
                    if attempt == max_attempts:
                        log("send", "abandon", f"{g['name']} 放弃，后续群继续")
        self.history.add(task)
        if len(result.delivered) < len(recipients):
            return finish("partial", f"送达 {len(result.delivered)}/{len(recipients)} 个群，失败的已记录")
        return finish("sent", f"按固定顺序送达 {len(recipients)} 个群")
