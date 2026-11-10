import contextlib
import io
import os
import sys
import tempfile
import time as _time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import orb_day, random_days  # noqa: E402
from groww_trader import runner  # noqa: E402
from groww_trader.config import read_json  # noqa: E402
from groww_trader.data import csv_path, save_csv  # noqa: E402
from groww_trader.market import IST  # noqa: E402

DAY = date(2026, 10, 20)


def at(h, m):
    return datetime(2026, 10, 20, h, m, tzinfo=IST)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["GTRADE_HOME"] = self.tmp.name
        for k in ("GROWW_ACCESS_TOKEN", "GROWW_API_KEY", "GROWW_TOTP_TOKEN", "GROWW_TOTP_SECRET",
                  "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GTRADE_MONGO_URI"):
            os.environ.pop(k, None)

    def tearDown(self):
        sys.stdout = sys.__stdout__
        os.environ.pop("GTRADE_HOME", None)
        self.tmp.cleanup()


class RunnerUnits(Base):
    def test_lock_is_exclusive(self):
        a, b = runner.Lock("t"), runner.Lock("t")
        self.assertTrue(a.acquire())
        self.assertFalse(b.acquire())
        a.release()
        self.assertTrue(b.acquire())
        b.release()

    def test_start_restart_done(self):
        s = runner.mark_start(at(8, 55))
        self.assertFalse(s["restart"])
        runner.mark_step(at(10, 0))
        s = runner.mark_start(at(11, 0))      # previous run never finished
        self.assertTrue(s["restart"])
        self.assertEqual(s["restarts"], 1)
        self.assertEqual(s["last_step"][11:16], "10:00")
        runner.mark_done(at(15, 41))
        self.assertTrue(runner.is_done(at(15, 50)))
        self.assertFalse(runner.is_done(at(15, 50) + timedelta(days=1)))  # new day

    def test_stale_alert_once_per_episode(self):
        runner.mark_start(at(8, 55))
        runner.mark_step(at(10, 0))
        sent = []
        self.assertIsNone(runner.alert_if_stuck(at(10, 10), sent.append))    # fine
        self.assertIsNotNone(runner.alert_if_stuck(at(10, 20), sent.append))  # stuck
        self.assertIsNone(runner.alert_if_stuck(at(10, 30), sent.append))     # already told
        runner.mark_step(at(10, 35))
        self.assertIsNotNone(runner.alert_if_stuck(at(10, 55), sent.append))  # new episode
        self.assertEqual(len(sent), 2)
        self.assertIn("10:00", sent[0])
        self.assertIsNone(runner.alert_if_stuck(at(16, 0), sent.append))      # after hours

    def test_daily_log_cleanup(self):
        logs = Path(self.tmp.name, "logs")
        logs.mkdir()
        old = logs / "paper-2026-08-01.log"
        old.write_text("old")
        p = runner.daily_log(at(9, 0), keep_days=30, interactive=False)
        print("hello")
        sys.stdout.flush()
        sys.stdout = sys.__stdout__
        self.assertFalse(old.exists())
        self.assertIn("hello", p.read_text())


class RunLoop(Base):
    def _run(self, start, extra=()):
        import gtrade
        clock = [start]
        real_sleep = _time.sleep
        gtrade.now_ist = lambda: clock[0]
        _time.sleep = lambda s: clock.__setitem__(0, clock[0] + timedelta(seconds=s))
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                gtrade.main(["paper", "run", "TEST", "--source", "csv", "--no-log", *extra])
        finally:
            _time.sleep = real_sleep
            gtrade._LIVE.clear()
        return buf.getvalue()

    def test_full_day_then_repeat_is_noop_and_restart_detected(self):
        import gtrade
        real_now = gtrade.now_ist
        try:
            save_csv(random_days(DAY - timedelta(days=1), 1, seed=3, price=100) + orb_day(DAY),
                     csv_path("TEST", 5))
            # a run that "crashed": state says started, last step 10:00, not done
            runner.mark_start(at(8, 55))
            runner.mark_step(at(10, 0))
            out = self._run(at(11, 0))
            self.assertIn("(restart)", out)
            self.assertTrue(read_json("run_state.json")["done"])
            out2 = self._run(at(15, 50))
            self.assertIn("already finished", out2)
        finally:
            gtrade.now_ist = real_now


if __name__ == "__main__":
    unittest.main()
