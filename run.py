"""回放一个工作日的 10 个场景，输出 docs/index.html 与 docs/audit.jsonl。"""

from pathlib import Path

from assistant.report import render
from assistant.scenarios import run_all

ROOT = Path(__file__).resolve().parent


def main() -> None:
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    scenarios, bot = run_all(docs / "audit.jsonl")
    (docs / "index.html").write_text(render(scenarios, bot, bot.cfg), encoding="utf-8")
    for i, s in enumerate(scenarios, 1):
        status = s.result.status if s.result else "refused"
        reason = s.result.reason if s.result else s.note
        print(f"{i:>2}. [{s.guard}] {s.title}：{status} · {reason}")
    print(f"报告 → {docs / 'index.html'}")


if __name__ == "__main__":
    main()
