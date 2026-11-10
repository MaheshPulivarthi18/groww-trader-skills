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
from groww_trader.config import load_config  # noqa: E402
from groww_trader.costs import net_pnl, round_trip  # noqa: E402
from groww_trader.data import csv_path, load_csv, save_csv  # noqa: E402
from groww_trader.indicators import rsi  # noqa: E402
from groww_trader.market import IST, Candle  # noqa: E402
from groww_trader.plan import make_plan  # noqa: E402
from groww_trader.risk import check  # noqa: E402
from groww_trader.setups import detect  # noqa: E402
from groww_trader.sizing import size  # noqa: E402

DAY = date(2026, 10, 20)  # a Tuesday


def cfg():
    os.environ.pop("GTRADE_HOME", None)
    return load_config("/nonexistent/config.json")


class Costs(unittest.TestCase):
    def test_intraday_round_trip(self):
        c = round_trip(1000, 1010, 100, cfg()["charges"], "MIS")
        self.assertEqual(c["brokerage"], 40.0)   # 0.05% capped at ₹20 per order
        self.assertEqual(c["stt"], 25.25)        # 0.025% of sell value
        self.assertEqual(c["stamp"], 3.0)        # 0.003% of buy value
        self.assertAlmostEqual(c["total"], 82.73, places=2)

    def test_short_pnl_symmetry(self):
        p = net_pnl("SELL", 1010, 1000, 100, cfg()["charges"], "MIS")
        self.assertEqual(p["gross"], 1000.0)
        self.assertAlmostEqual(p["net"], 1000 - 82.73, places=2)


class Setups(unittest.TestCase):
    def setUp(self):
        self.c = cfg()
        self.bars = orb_day(DAY)

    def test_orb_triggers_on_first_close_above_range(self):
        s = detect("orb", "TEST", self.bars, self.c, 5)
        self.assertEqual(s["status"], "triggered")
        self.assertEqual((s["or_high"], s["or_low"], s["or_mid"]), (101.0, 100.0, 100.5))
        self.assertEqual(s["entry"], 101.6)
        self.assertTrue(s["trigger_time"].startswith("2026-10-20T09:40"))

    def test_orb_waiting_before_trigger_and_during_range(self):
        at = datetime(2026, 10, 20, 9, 37, tzinfo=IST)  # 09:35 bar still forming
        self.assertEqual(detect("orb", "TEST", self.bars, self.c, 5, at=at)["status"], "waiting")
        at = datetime(2026, 10, 20, 9, 25, tzinfo=IST)
        self.assertEqual(detect("orb", "TEST", self.bars, self.c, 5, at=at)["status"], "waiting")

    def test_orb_expired_when_window_closed(self):
        flat = [Candle(b.ts, 100.5, 100.9, 100.1, 100.5) for b in self.bars]  # never breaks out
        self.c["risk"]["no_entry_after"] = "10:00"
        self.assertEqual(detect("orb", "TEST", flat, self.c, 5)["status"], "expired")

    def test_pdh_breakout(self):
        prev = [Candle(b.ts - timedelta(days=1), 100, 101.2, 99.5, 100.4) for b in self.bars]
        s = detect("pdh_breakout", "TEST", self.bars, self.c, 5, prev_bars=prev)
        self.assertEqual((s["status"], s["side"], s["entry"]), ("triggered", "BUY", 101.6))

    def test_short_only_when_allowed(self):
        down = [Candle(b.ts, 200 - (b.open - 100), 200 - (b.low - 100), 200 - (b.high - 100),
                       200 - (b.close - 100)) for b in self.bars]  # mirror image
        self.assertNotEqual(detect("orb", "T", down, self.c, 5).get("side"), "SELL")
        self.c["allow_short"] = True
        self.assertEqual(detect("orb", "T", down, self.c, 5)["side"], "SELL")


class PlanSizeRisk(unittest.TestCase):
    def setUp(self):
        self.c = cfg()
        self.sig = detect("orb", "TEST", orb_day(DAY), self.c, 5)

    def test_plan(self):
        p = make_plan(self.sig, self.c["exit"])
        self.assertEqual((p["stop"], p["risk_per_share"]), (100.5, 1.1))
        self.assertEqual(p["target"], 103.25)  # 101.6 + 1.5 * 1.1
        self.assertTrue(p["flat_by"].startswith("2026-10-20T15:10"))
        self.assertEqual(make_plan(self.sig, {**self.c["exit"], "stop": "pct:1"})["stop"], 100.6)

    def test_size_respects_capital_and_risk(self):
        o = size(make_plan(self.sig, self.c["exit"]), self.c)
        self.assertEqual(o["qty"], 246)  # 25% of ₹1,00,000 / 101.6
        self.assertEqual(o["limited_by"], "capital")
        self.assertLessEqual(-o["loss_at_stop"], self.c["risk"]["max_loss_per_trade"])
        self.c["risk"]["max_loss_per_trade"] = 100
        o = size(make_plan(self.sig, self.c["exit"]), self.c)
        self.assertLessEqual(-o["loss_at_stop"], 100)
        self.assertEqual(o["limited_by"], "risk")

    def test_risk_pass_and_blocks(self):
        o = size(make_plan(self.sig, self.c["exit"]), self.c)
        now = datetime(2026, 10, 20, 9, 41, tzinfo=IST)
        self.assertEqual(check([o], self.c, [], now=now)[0]["risk_check"], "PASS")
        late = datetime(2026, 10, 20, 14, 45, tzinfo=IST)
        self.assertEqual(check([o], self.c, [], now=late)[0]["risk_check"], "BLOCK")
        journal = [{"day": "2026-10-20", "status": "closed", "net": -1600}]
        r = check([o], self.c, journal, now=now)[0]
        self.assertEqual(r["risk_check"], "BLOCK")
        self.assertTrue(any("daily loss" in x for x in r["risk_reasons"]))
        r = check([{**o, "side": "SELL"}], self.c, [], now=now)[0]
        self.assertIn("short selling is off (allow_short: false)", r["risk_reasons"])

    def test_risk_trade_count_includes_batch(self):
        o = size(make_plan(self.sig, self.c["exit"]), self.c)
        self.c["risk"]["max_trades_per_day"] = 1
        self.c["risk"]["max_open_positions"] = 5
        res = check([o, dict(o)], self.c, [], now=None)
        self.assertEqual([r["risk_check"] for r in res], ["PASS", "BLOCK"])


class Backtest(unittest.TestCase):
    def test_designed_day_hits_target(self):
        c = cfg()
        prev = random_days(DAY - timedelta(days=1), 1, seed=3, price=100)
        res = bt.run("TEST", prev + orb_day(DAY), "orb", c, 5)
        t = [x for x in res["trades"] if x["day"] == str(DAY)][0]
        self.assertEqual(t["exit_reason"], "target")
        self.assertEqual(t["fill_exit"], round(103.25 * (1 - 0.0002), 2))
        self.assertGreater(t["net"], 0)

    def test_random_history_stats_consistent(self):
        c = cfg()
        res = bt.run("RAND", random_days(date(2026, 8, 3), 40, seed=11), "orb", c, 5)
        s = res["stats"]
        self.assertEqual(res["sessions"], 40)
        if s["trades"]:
            self.assertEqual(s["wins"] + s["losses"], s["trades"])
            self.assertAlmostEqual(s["net_total"], sum(t["net"] for t in res["trades"]), places=1)
            self.assertAlmostEqual(s["net_total"], s["gross_total"] - s["charges_total"], places=1)
            for t in res["trades"]:
                self.assertLessEqual(-t["net"], c["risk"]["max_loss_per_trade"] * 3)  # gaps can exceed plan
        out1 = bt.bootstrap(res["trades"])
        self.assertEqual(out1, bt.bootstrap(res["trades"]))  # seeded, repeatable


class Credentials(unittest.TestCase):
    def test_totp_secret_cleanup_and_errors(self):
        from groww_trader.data import normalize_totp_secret
        self.assertEqual(normalize_totp_secret(" jbsw y3dp-ehpk 3pxp "), "JBSWY3DPEHPK3PXP")
        self.assertEqual(normalize_totp_secret("JBSWY3DPEHPK3PX"), "JBSWY3DPEHPK3PX=")
        with self.assertRaises(RuntimeError) as e:
            normalize_totp_secret("paste_totp_secret_here")
        self.assertIn("swap", str(e.exception))
        self.assertNotIn("PASTE", str(e.exception))  # never echo the secret
        with self.assertRaises(RuntimeError):
            normalize_totp_secret("eyJhbGciOi.J9.x1")


class CandleParsing(unittest.TestCase):
    def test_skips_rows_with_missing_prices(self):
        from groww_trader.data import parse_candle_rows
        rows = [
            [1760932500, 812.0, 813.5, 811.2, 813.0, 15000],       # epoch seconds
            ["2026-10-20T09:20:00", 813.0, 814.0, 812.5, 813.8, None],  # no volume
            [1760933100, None, None, None, None, None],            # no trades: skip
            [None, 1, 2, 0.5, 1.5, 10],                             # no time: skip
            [1760933400, "814", "815", "813", "814.5"],             # strings, 5 fields
            {"timestamp": "2026-10-20 09:35:00", "open": 1, "high": 2, "low": 0.5,
             "close": 1.5, "volume": 7},
            [1760933700, 1.0],                                      # short row: skip
        ]
        out = parse_candle_rows(rows)
        self.assertEqual(len(out), 4)
        self.assertEqual(out[0].ts.strftime("%H:%M"), "09:25")
        self.assertEqual(out[1].volume, 0.0)
        self.assertEqual(out[2].close, 814.5)
        self.assertEqual(parse_candle_rows(None), [])


class Indicators(unittest.TestCase):
    def test_rsi_extremes(self):
        self.assertEqual(rsi(list(range(1, 30)))[-1], 100.0)
        self.assertEqual(rsi(list(range(30, 1, -1)))[-1], 0.0)


class CLI(unittest.TestCase):
    def test_pipeline_offline(self):
        import gtrade
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GTRADE_HOME"] = tmp
            for k in ("GROWW_ACCESS_TOKEN", "GROWW_API_KEY", "GROWW_TOTP_TOKEN", "GROWW_TOTP_SECRET"):
                os.environ.pop(k, None)
            try:
                bars = random_days(DAY - timedelta(days=1), 1, seed=3, price=100) + orb_day(DAY)
                save_csv(bars, csv_path("TEST", 5))
                self.assertEqual(len(load_csv(csv_path("TEST", 5))), len(bars))
                run = lambda *a: gtrade.main(list(a))
                with contextlib.redirect_stdout(io.StringIO()):
                    run("scan", "TEST", "--setup", "orb", "--write")
                    run("plan", "--write")
                    run("size", "--write")
                    run("risk", "--now", "2026-10-20T09:41", "--write")
                    run("backtest", "TEST", "--setup", "orb", "--days", "10", "--write")
                orders = json.loads(Path(tmp, "orders.json").read_text())["orders"]
                self.assertEqual(orders[0]["risk_check"], "PASS")
                self.assertTrue(orders[0]["paper"])
                bt_res = json.loads(Path(tmp, "backtest.json").read_text())
                self.assertGreaterEqual(bt_res["stats"]["trades"], 1)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    run("show")
                self.assertIn("[PASS] [PAPER] Buy 246 TEST", buf.getvalue())
            finally:
                os.environ.pop("GTRADE_HOME", None)


if __name__ == "__main__":
    unittest.main()
