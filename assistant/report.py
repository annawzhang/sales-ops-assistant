"""生成场景回放页：每个场景的触发方式、经过的步骤、护栏结果和审计日志。"""

from collections import Counter
from html import escape

CSS = """
:root { --text:#0f172a; --muted:#64748b; --border:#e2e8f0; --accent:#2563eb; --bg:#f8fafc; }
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text); }
.wrap { max-width:1120px; margin:0 auto; padding:30px 22px 48px; }
h1 { margin:0 0 6px; font-size:1.55rem; } h2 { font-size:1.02rem; margin:30px 0 12px; }
.meta { color:var(--muted); font-size:0.86rem; line-height:1.7; }
.badge { display:inline-block; margin-left:8px; padding:1px 8px; border-radius:999px; background:#fef3c7; color:#92400e; font-size:0.74rem; }
.grid { display:grid; gap:14px; } .g4 { grid-template-columns:repeat(4,1fr); } .g2 { grid-template-columns:1fr 1fr; } .g3 { grid-template-columns:repeat(3,1fr); }
@media (max-width:860px) { .g4,.g2,.g3 { grid-template-columns:1fr; } }
.card { background:#fff; border:1px solid var(--border); border-radius:12px; padding:16px; }
.kpi .label { color:var(--muted); font-size:0.78rem; } .kpi .value { font-size:1.45rem; font-weight:700; margin-top:4px; } .kpi .sub { color:var(--muted); font-size:0.76rem; margin-top:3px; }
.pipe { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
.pipe div { flex:1; min-width:120px; background:#fff; border:1px solid var(--border); border-radius:10px; padding:10px; font-size:0.78rem; }
.pipe b { display:block; font-size:0.84rem; margin-bottom:2px; color:#1e3a8a; }
.layer { font-size:0.8rem; line-height:1.7; } .layer b { color:#1e3a8a; }
.sc { display:grid; grid-template-columns:200px 1fr; gap:14px; }
@media (max-width:860px) { .sc { grid-template-columns:1fr; } }
.sc h3 { margin:0 0 4px; font-size:0.92rem; } .trigger { font-size:0.78rem; color:#334155; background:#f1f5f9; border-radius:8px; padding:6px 8px; margin-top:8px; }
.guard { display:inline-block; font-size:0.72rem; padding:1px 7px; border-radius:6px; background:#eff6ff; color:#1d4ed8; }
.st { display:inline-block; font-size:0.74rem; font-weight:700; padding:2px 8px; border-radius:6px; margin-top:8px; }
.st-sent { background:#dcfce7; color:#166534; } .st-partial { background:#fef9c3; color:#854d0e; }
.st-skipped, .st-refused { background:#f1f5f9; color:#475569; }
.st-blocked, .st-failed { background:#fee2e2; color:#991b1b; } .st-pending_approval { background:#fef3c7; color:#92400e; }
.steps { list-style:none; margin:0; padding:0; font-size:0.78rem; }
.steps li { display:grid; grid-template-columns:96px 70px 1fr; gap:8px; padding:4px 0; border-bottom:1px dashed var(--border); }
.steps li:last-child { border-bottom:none; }
.s-ok, .s-auto, .s-approved { color:#047857; } .s-error, .s-fail, .s-stop, .s-abandon { color:#b91c1c; } .s-skip, .s-wait, .s-pending { color:#b45309; }
code { font-size:0.74rem; background:#f1f5f9; padding:1px 4px; border-radius:4px; }
pre { background:#0f172a; color:#e2e8f0; padding:12px; border-radius:8px; font-size:0.74rem; overflow:auto; margin:0; white-space:pre-wrap; }
table { width:100%; border-collapse:collapse; font-size:0.76rem; }
th, td { text-align:left; padding:5px 6px; border-bottom:1px solid var(--border); }
th { color:var(--muted); font-weight:600; }
.muted { color:var(--muted); font-size:0.78rem; line-height:1.6; }
footer { margin-top:36px; color:var(--muted); font-size:0.78rem; }
"""

STATUS_NAMES = {"sent": "已发送", "partial": "部分送达", "skipped": "跳过", "blocked": "已拦截",
                "failed": "失败未发送", "pending_approval": "待确认", "refused": "拒绝执行"}
STEP_NAMES = {"lock": "幂等锁", "window": "时间护栏", "refresh": "数据刷新", "retry": "重试", "health_check": "健康检查",
              "render": "渲染", "recipients": "收件人", "preview": "预览确认", "send": "发送", "finish": "结束"}


def scenario_card(i: int, s) -> str:
    status = s.result.status if s.result else "refused"
    if s.result:
        steps = "".join(f"<li><span>{STEP_NAMES.get(e['step'], e['step'])}</span><span class='s-{e['status']}'>{e['status']}</span>"
                        f"<span>{escape(e['detail'])}</span></li>" for e in s.result.events if e["step"] != "finish")
        reason = s.result.reason
    else:
        steps = (f"<li><span>意图识别</span><span class='s-stop'>refuse</span><span>识别为「{s.plan.task}」，"
                 f"但请求越出了任务配置</span></li>")
        reason = s.note
    return f"""<div class="card sc">
      <div><span class="guard">{escape(s.guard)}</span><h3 style="margin-top:6px">{i}. {escape(s.title)}</h3>
        <div class="trigger">{escape(s.trigger)}</div>
        <div class="st st-{status}">{STATUS_NAMES[status]}</div></div>
      <div><ul class="steps">{steps}</ul><div class="muted" style="margin-top:6px">结果：{escape(reason)}</div></div>
    </div>"""


def render(scenarios, bot, cfg) -> str:
    statuses = Counter(s.result.status if s.result else "refused" for s in scenarios)
    messages = sum(len(s.result.delivered) for s in scenarios if s.result)
    guarded = sum(statuses[k] for k in ("skipped", "blocked", "failed", "refused", "pending_approval"))
    sample = next(s for s in scenarios if s.result and s.result.status == "sent" and s.result.task == "attainment")
    plan = next(s.plan for s in scenarios if s.plan and not s.plan.unclear)
    delivered = "".join(f"<tr><td>{escape(d['group'])}</td><td><code>{d['message_id']}</code></td></tr>" for d in sample.result.delivered)
    audit_rows = "".join(
        f"<tr><td>{e['time'][11:]}</td><td><code>{e['run_id']}</code></td><td>{STEP_NAMES.get(e['step'], e['step'])}</td>"
        f"<td class='s-{e['status']}'>{e['status']}</td><td>{escape(e['detail'])}</td></tr>"
        for e in bot.audit if e["step"] in ("send", "finish", "health_check", "lock", "window"))
    w = cfg["send_window"]
    wrong = sum(1 for m in bot.outbox.sent if bot.groups[m["group"]].get("muted") or bot.groups[m["group"]].get("sensitive"))
    slots = [(m["group"], m["run_id"].split("-")[0], m["run_id"].split("-")[1][:8], int(m["run_id"][-6:-4]) < 13)
             for m in bot.outbox.sent]
    duplicate = len(slots) - len(set(slots))
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Sales Ops Assistant · 区域销售 AI 助手</title><style>{CSS}</style></head>
<body><div class="wrap">
  <h1>Sales Ops Assistant · 区域销售 AI 助手</h1>
  <div class="meta">一句话提需求 → 拆成确定性步骤 → 程序算数 → 健康检查 → 预览确认 → 固定顺序发送 → message_id 留痕
    <span class="badge">虚构门店与群组，模拟数据</span></div>

  <div class="pipe">
    <div><b>1 数据刷新</b>多源抓取，偶发失败完整重跑一次</div>
    <div><b>2 计算渲染</b>达成率、排名由程序计算，不交给模型</div>
    <div><b>3 健康检查</b>覆盖率 · 新鲜度 · 数值合理</div>
    <div><b>4 预览确认</b>首次运行或群发超过 {cfg['approval']['max_groups_without_approval']} 个群需确认</div>
    <div><b>5 发送留痕</b>白名单 · 禁言群跳过 · message_id</div>
  </div>

  <div class="grid g4" style="margin-top:16px">
    <div class="card kpi"><div class="label">回放场景</div><div class="value">{len(scenarios)} 个</div><div class="sub">模拟一个工作日（{scenarios[0].result.events[0]['time'][:10]}）</div></div>
    <div class="card kpi"><div class="label">成功送达</div><div class="value">{messages} 条消息</div><div class="sub">{statuses['sent']} 次运行全部送达</div></div>
    <div class="card kpi"><div class="label">被护栏拦下</div><div class="value">{guarded} 次</div><div class="sub">跳过 {statuses['skipped']} · 拦截 {statuses['blocked']} · 失败 {statuses['failed']} · 拒绝 {statuses['refused']} · 待确认 {statuses['pending_approval']}</div></div>
    <div class="card kpi"><div class="label">错发 / 重复发送</div><div class="value">{wrong} / {duplicate}</div><div class="sub">按 outbox 实际发送记录核对 · 发送窗口 {w['start']}–{w['end']}</div></div>
  </div>

  <h2>一句话 → 执行计划</h2>
  <div class="grid g2">
    <div class="card"><div class="muted">用户输入</div><div style="margin:4px 0 10px">「{escape(plan.text)}」</div>
      <table><tbody>
        <tr><th>识别任务</th><td>{cfg['tasks'][plan.task]['name']}（<code>{plan.task}</code>）</td></tr>
        <tr><th>区域</th><td>{'、'.join(plan.regions)}</td></tr>
        <tr><th>产出</th><td>{'卡片 / 图' if plan.want_chart else '文字'}{' + 发送' if plan.send else ''}</td></tr>
        <tr><th>步骤</th><td>{' → '.join(plan.steps)}</td></tr>
      </tbody></table></div>
    <div class="card"><div class="muted" style="margin-bottom:6px">发送内容（场景 3）</div><pre>{escape(sample.result.preview)}</pre>
      <table style="margin-top:10px"><thead><tr><th>群（固定顺序）</th><th>message_id</th></tr></thead><tbody>{delivered}</tbody></table></div>
  </div>

  <h2>场景回放</h2>
  <div class="grid">{''.join(scenario_card(i, s) for i, s in enumerate(scenarios, 1))}</div>

  <h2>审计日志（节选，完整版见 docs/audit.jsonl）</h2>
  <div class="card"><table><thead><tr><th>时间</th><th>run_id</th><th>步骤</th><th>状态</th><th>详情</th></tr></thead><tbody>{audit_rows}</tbody></table></div>

  <footer>由 run.py 生成 · 配置见 config/assistant.toml · © 2026 张文婧 (Anna Zhang) · github.com/annawzhang · MIT · 保留署名</footer>
</div></body></html>
"""
