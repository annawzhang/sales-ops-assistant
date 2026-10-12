import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant.data import Faults, Sources
from assistant.intents import route
from assistant.pipeline import Assistant, Outbox, load_config
from assistant.scenarios import run_all

NOON = datetime(2026, 10, 12, 11, 0)


def make_bot(faults=None, outbox_fail=0):
    bot = Assistant(load_config(), Sources(seed=3, faults=faults), Outbox(outbox_fail))
    bot.history.update(bot.cfg["tasks"])
    return bot


class RouterTest(unittest.TestCase):
    def test_routes_task_and_region(self):
        p = route("把深圳门店的达成进度发到群里")
        self.assertEqual((p.task, p.regions, p.send), ("attainment", ["华南"], True))

    def test_unknown_and_overreach(self):
        self.assertIsNotNone(route("今天天气怎么样").unclear)
        self.assertIn("所有群", route("库存发到所有群").unclear)


class PipelineTest(unittest.TestCase):
    def test_lock_prevents_duplicate(self):
        bot = make_bot()
        self.assertEqual(bot.run("inventory", NOON).status, "sent")
        self.assertEqual(bot.run("inventory", NOON.replace(minute=30)).status, "skipped")
        self.assertEqual(bot.run("inventory", NOON.replace(hour=15)).status, "sent")

    def test_window_guard(self):
        self.assertEqual(make_bot().run("inventory", NOON.replace(hour=22)).status, "blocked")

    def test_retry_once_then_give_up(self):
        ok = make_bot(Faults(fail_calls={1})).run("inventory", NOON)
        self.assertEqual((ok.status, ok.attempts), ("sent", 2))
        bad_bot = make_bot(Faults(fail_calls={1, 2}))
        bad = bad_bot.run("inventory", NOON)
        self.assertEqual(bad.status, "failed")
        self.assertEqual(bad_bot.outbox.sent, [])

    def test_health_check_blocks_send(self):
        bot = make_bot(Faults(spike_store="杭州西湖"))
        r = bot.run("attainment", NOON, approved_by="负责人")
        self.assertEqual(r.status, "blocked")
        self.assertEqual(bot.outbox.sent, [])

    def test_muted_and_sensitive_groups_never_receive(self):
        bot = make_bot()
        bot.run("attainment", NOON, approved_by="负责人")
        groups = [m["group"] for m in bot.outbox.sent]
        self.assertEqual(groups, ["g-mgmt", "g-east", "g-south"])

    def test_approval_required_for_wide_broadcast(self):
        r = make_bot().run("attainment", NOON)
        self.assertEqual(r.status, "pending_approval")

    def test_send_retry_records_message_id(self):
        bot = make_bot(outbox_fail=1)
        r = bot.run("inventory", NOON)
        self.assertEqual(r.status, "sent")
        self.assertTrue(all(d["message_id"].startswith("om_") for d in r.delivered))


class ScenarioTest(unittest.TestCase):
    def test_day_replay(self):
        scenarios, bot = run_all()
        statuses = [s.result.status if s.result else "refused" for s in scenarios]
        self.assertEqual(statuses, ["blocked", "pending_approval", "sent", "skipped", "sent",
                                    "blocked", "blocked", "sent", "failed", "refused"])
        self.assertEqual(len(bot.outbox.sent), 7)


if __name__ == "__main__":
    unittest.main()
