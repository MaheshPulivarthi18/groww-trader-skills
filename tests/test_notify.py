import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import orb_day, random_days  # noqa: E402
from groww_trader import notify, paper  # noqa: E402
from groww_trader.config import load_config  # noqa: E402
from groww_trader.market import IST  # noqa: E402

DAY = date(2026, 10, 20)
TOKEN = "123456:ABCdefSECRET"


class FakeHTTP:
    def __init__(self, updates=None, fail=False):
        self.sent, self.updates, self.fail = [], updates or [], fail

    def __call__(self, method, params):
        if self.fail:
            raise OSError(f"cannot reach https://api.telegram.org/bot{TOKEN}/{method}")
        if method == "sendMessage":
            self.sent.append(params["text"])
            return {"ok": True}
        if method == "getUpdates":
            off = params.get("offset", 0)
            return {"ok": True, "result": [u for u in self.updates if u["update_id"] >= off]}
        return {"ok": False, "description": "bad method"}


def upd(uid, chat, text):
    return {"update_id": uid, "message": {"chat": {"id": chat, "type": "private"}, "text": text}}


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["GTRADE_HOME"] = self.tmp.name

    def tearDown(self):
        os.environ.pop("GTRADE_HOME", None)
        self.tmp.cleanup()

    def test_disabled_without_env(self):
        for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            os.environ.pop(k, None)
        t = notify.Telegram()
        self.assertFalse(t.enabled)
        self.assertFalse(t.send("x"))
        self.assertEqual(t.poll(), [])

    def test_only_owner_commands_and_offset(self):
        http = FakeHTTP([upd(1, 42, "/status"), upd(2, 999, "/pause"), upd(3, 42, "/pause@mybot now")])
        t = notify.Telegram(TOKEN, "42", http=http)
        self.assertEqual(t.poll(), ["/status", "/pause"])  # stranger's /pause ignored
        self.assertEqual(t.poll(), [])                       # offset remembered
        self.assertEqual(json.loads(Path(self.tmp.name, "telegram_state.json").read_text()), {"offset": 4})

    def test_pause_resume_and_replies(self):
        r = notify.handle(["/pause"], lambda: "s", lambda: "r")
        self.assertTrue(notify.is_paused())
        self.assertIn("Paused", r[0])
        self.assertIn("PAUSED", notify.handle(["/status"], lambda: "open 0", lambda: "r")[0])
        notify.handle(["/resume"], lambda: "s", lambda: "r")
        self.assertFalse(notify.is_paused())
        self.assertIn("Unknown", notify.handle(["/buy"], lambda: "s", lambda: "r")[0])

    def test_send_events_filters_and_failure_is_quiet(self):
        http = FakeHTTP()
        t = notify.Telegram(TOKEN, "42", http=http)
        when = datetime(2026, 10, 20, 9, 40, tzinfo=IST)
        self.assertTrue(t.send_events(["SIGNAL SBIN orb BUY", "random noise"], when))
        self.assertEqual(http.sent, ["[09:40] paper\nSIGNAL SBIN orb BUY"])
        logs = []
        bad = notify.Telegram(TOKEN, "42", log=logs.append, http=FakeHTTP(fail=True))
        self.assertFalse(bad.send("a"))
        self.assertFalse(bad.send("b"))
        self.assertEqual(len(logs), 1)              # one warning per outage
        self.assertNotIn("SECRET", logs[0])          # token scrubbed


class PausedPaper(unittest.TestCase):
    def test_paused_blocks_new_and_still_exits_open(self):
        c = load_config("/nonexistent")
        c["setups"] = {"orb": c["setups"]["orb"]}
        bars = random_days(DAY - timedelta(days=1), 1, seed=3, price=100) + orb_day(DAY)
        data = {"TEST": bars}
        at = lambda h, m: datetime(2026, 10, 20, h, m, tzinfo=IST)
        j, ev = paper.step(c, data, at(9, 40), [], 5, paused=True)
        self.assertEqual((j[0]["status"], j[0]["risk_reasons"]), ("blocked", ["paused"]))
        # open a position unpaused, then pause: it must still reach its exit
        j, _ = paper.step(c, data, at(9, 40), [], 5)
        self.assertEqual(j[0]["status"], "open")
        t = at(9, 45)
        while j[0]["status"] == "open" and t <= at(15, 30):
            j, _ = paper.step(c, data, t, j, 5, paused=True)
            t += timedelta(minutes=5)
        self.assertEqual((j[0]["status"], j[0]["exit_reason"]), ("closed", "target"))


if __name__ == "__main__":
    unittest.main()
