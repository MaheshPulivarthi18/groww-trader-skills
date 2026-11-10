import contextlib
import io
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
from groww_trader import backtest as bt  # noqa: E402
from groww_trader import paper  # noqa: E402
from groww_trader.config import load_config  # noqa: E402
from groww_trader.data import csv_path, save_csv  # noqa: E402
from groww_trader.market import IST, Candle  # noqa: E402

DAY = date(2026, 10, 20)


def cfg():
    c = load_config("/nonexistent/config.json")
    c["setups"] = {"orb": c["setups"]["orb"]}  # one setup keeps the assertions simple
    return c


def history():
    return random_days(DAY - timedelta(days=1), 1, seed=3, price=100) + orb_day(DAY)


def at(hh, mm):
    return datetime(2026, 10, 20, hh, mm, tzinfo=IST)


class PaperStep(unittest.TestCase):
    def test_replay_matches_backtest(self):
        c = cfg()
        journal, log = paper.replay(c, {"TEST": history()}, DAY, 5)
        self.assertEqual(len(journal), 1)
        e = journal[0]
        self.assertEqual((e["status"], e["exit_reason"]), ("closed", "target"))
        t = [x for x in bt.run("TEST", history(), "orb", c, 5)["trades"] if x["day"] == str(DAY)][0]
        for k in ("fill_entry", "fill_exit", "net", "qty"):
            self.assertEqual(e[k], t[k], k)  # paper and backtest share one rule book
        self.assertTrue(any("SIGNAL" in x for x in log) and any("CLOSED" in x for x in log))

    def test_no_peeking_and_idempotent(self):
        c = cfg()
        data = {"TEST": history()}
        j, ev = paper.step(c, data, at(9, 38), [], 5)
        self.assertEqual(j, [])  # trigger bar (09:35) has not closed yet
        j, ev = paper.step(c, data, at(9, 40), j, 5)
        self.assertEqual(j[0]["status"], "open")
        self.assertEqual(j[0]["entry_time"][11:16], "09:40")
        j2, ev2 = paper.step(c, data, at(9, 40), json.loads(json.dumps(j)), 5)
        self.assertEqual(j2, j)       # same moment twice changes nothing
        self.assertEqual(ev2, [])
        j, _ = paper.step(c, data, at(9, 45), j, 5)
        self.assertEqual(j[0]["status"], "open")  # stop/target not reached yet

    def test_late_start_records_missed(self):
        c = cfg()
        j, ev = paper.step(c, {"TEST": history()}, at(11, 0), [], 5)
        self.assertEqual(j[0]["status"], "missed")
        self.assertTrue(ev[0].startswith("MISSED"))

    def test_risk_block_recorded_and_not_counted(self):
        c = cfg()
        prior = [{"id": "x", "mode": "paper", "day": str(DAY), "status": "closed", "net": -1600}]
        j, ev = paper.step(c, {"TEST": history()}, at(9, 40), list(prior), 5)
        self.assertEqual(j[-1]["status"], "blocked")
        self.assertTrue(any("daily loss" in r for r in j[-1]["risk_reasons"]))

    def test_stop_out_and_flat_by(self):
        c = cfg()
        bars = orb_day(DAY)
        crash = [b if b.ts < at(9, 50) else Candle(b.ts, 100.4, 100.45, 100.3, 100.35) for b in bars]
        data = {"TEST": random_days(DAY - timedelta(days=1), 1, seed=3, price=100) + crash}
        j, _ = paper.replay(c, data, DAY, 5)
        self.assertEqual((j[0]["exit_reason"], j[0]["status"]), ("stop", "closed"))
        self.assertLess(j[0]["net"], 0)
        c["exit"]["target"] = "50R"  # unreachable: must leave at flat-by
        j, _ = paper.replay(c, {"TEST": history()}, DAY, 5)
        self.assertEqual(j[0]["exit_reason"], "time")
        self.assertEqual(j[0]["exit_time"][11:16], "15:10")

    def test_report(self):
        j, _ = paper.replay(cfg(), {"TEST": history()}, DAY, 5)
        r = paper.report(j)
        self.assertEqual(r["stats"]["trades"], 1)
        self.assertEqual(r["by_day"][0]["day"], str(DAY))
        self.assertEqual(r["ideas"], {"closed": 1})

    def test_next_boundary(self):
        self.assertEqual(paper.next_boundary(at(9, 41), 5, lag_s=20), at(9, 45) + timedelta(seconds=20))
        self.assertEqual(paper.next_boundary(at(8, 0), 5, lag_s=0), at(9, 20))


class PaperCLI(unittest.TestCase):
    def test_once_and_replay_offline(self):
        import gtrade
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GTRADE_HOME"] = tmp
            for k in ("GROWW_ACCESS_TOKEN", "GROWW_API_KEY", "GROWW_TOTP_TOKEN", "GROWW_TOTP_SECRET"):
                os.environ.pop(k, None)
            try:
                save_csv(history(), csv_path("TEST", 5))
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    gtrade.main(["paper", "once", "TEST", "--now", "2026-10-20T09:40"])
                    gtrade.main(["paper", "once", "TEST", "--now", "2026-10-20T12:00"])
                    gtrade.main(["paper", "replay", "TEST", "--date", "2026-10-20", "--write"])
                    gtrade.main(["paper", "report"])
                text = buf.getvalue()
                self.assertIn("FILLED", text)
                self.assertIn("CLOSED", text)
                j = json.loads(Path(tmp, "journal.json").read_text())
                self.assertEqual(j[0]["status"], "closed")
                self.assertTrue(Path(tmp, "journal_replay.json").exists())
            finally:
                os.environ.pop("GTRADE_HOME", None)


if __name__ == "__main__":
    unittest.main()


class IncrementalFetch(unittest.TestCase):
    def test_second_step_fetches_only_today(self):
        import gtrade

        class FakeGroww:
            name = "groww"

            def __init__(self):
                self.calls = []

            def candles(self, symbol, interval, start, end):
                self.calls.append((start, end))
                return [c for c in history() if start <= c.ts <= end]

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GTRADE_HOME"] = tmp
            gtrade._LIVE.clear()
            try:
                src = FakeGroww()
                d1, e1 = gtrade._paper_data(src, ["TEST"], 5)
                d2, e2 = gtrade._paper_data(src, ["TEST"], 5)
                self.assertEqual((e1, e2), ({}, {}))
                (s1, _), (s2, _) = src.calls
                self.assertGreaterEqual((s2 - s1).days, 6)         # 2nd call: today only
                self.assertEqual(s2.strftime("%H:%M"), "09:00")
                self.assertEqual(len(d2["TEST"]), len(d1["TEST"]))  # merged, no duplicates
                self.assertTrue(csv_path("TEST", 5).exists())
            finally:
                gtrade._LIVE.clear()
                os.environ.pop("GTRADE_HOME", None)
