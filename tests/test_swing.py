import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from groww_trader import swing  # noqa: E402
from groww_trader.config import load_config  # noqa: E402
from groww_trader.costs import round_trip  # noqa: E402
from groww_trader.market import IST, Candle  # noqa: E402


def days(prices):
    """prices: list of (o, h, l, c), one per weekday from 2026-01-05."""
    out, d = [], date(2026, 1, 5)
    for o, h, l, c in prices:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append(Candle(datetime(d.year, d.month, d.day, tzinfo=IST), o, h, l, c, 1e5))
        d += timedelta(days=1)
    return out


FLAT = [(100, 101, 99, 100)] * 25


class Swing(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config("/nonexistent")

    def test_breakout_entry_next_open_and_target(self):
        series = days(FLAT + [(100, 102.5, 100, 102)] + [(102.2, 103, 102, 102.8)] +
                      [(103, 110, 103, 109)] + [(109, 110, 108, 109)] * 3)
        rule = {"lookback": 20, "stop": "pct:3", "target": "2R", "hold": 10, "trend": 0}
        t = swing.run("X", series, rule, self.cfg)["trades"][0]
        self.assertEqual(t["signal_day"], str(series[25].ts.date()))
        self.assertEqual(t["fill_entry"], round(102.2 * 1.0003, 2))   # next day's open + slippage
        self.assertEqual(t["stop"], 98.94)                            # 3% under the signal close
        self.assertEqual((t["exit_reason"], t["fill_exit"]), ("target", 108.12))  # 102 + 2 x 3.06
        self.assertGreater(t["charges"], 0)

    def test_stop_and_time_exits(self):
        down = days(FLAT + [(100, 102.5, 100, 102)] + [(101, 101.5, 97, 97.5)] + [(97.5, 98, 97, 97.5)] * 3)
        rule = {"lookback": 20, "stop": "pct:3", "target": "none", "hold": 3, "trend": 0}
        t = swing.run("X", down, rule, self.cfg)["trades"][0]
        self.assertEqual(t["exit_reason"], "stop")
        self.assertLess(t["fill_exit"], 98.94)                        # extra stop slippage
        drift = days(FLAT + [(100, 102.5, 100, 102)] + [(102, 102.6, 101.5, 102.3)] * 5)
        t = swing.run("X", drift, rule, self.cfg)["trades"][0]
        self.assertEqual((t["exit_reason"], t["days_held"]), ("time", 3))

    def test_delivery_charges_include_dp_and_stt_both_sides(self):
        c = round_trip(1000, 1000, 10, self.cfg["charges"], "CNC")
        self.assertEqual(c["dp"], 20.0)
        self.assertEqual(c["stt"], 20.0)                              # 0.1% of 10k, twice
        self.assertEqual(round_trip(1000, 1000, 10, self.cfg["charges"], "MIS")["dp"], 0.0)

    def test_sweep_needs_enough_history(self):
        with self.assertRaises(ValueError):
            swing.sweep({"X": days(FLAT)}, self.cfg, swing.grid([20], ["pct:3"], ["2R"], [10], [0]))


if __name__ == "__main__":
    unittest.main()


class SwingRandomBaseline(unittest.TestCase):
    def test_baseline_runs_and_reports(self):
        import random as _r
        from groww_trader import swing as sw
        from groww_trader.config import load_config
        cfg = load_config("/nonexistent")
        rng = _r.Random(3)
        data = {}
        for k in range(4):
            p, cs, d = 100.0, [], date(2023, 1, 2)
            for n in range(600):
                while d.weekday() >= 5:
                    d += timedelta(days=1)
                o = p
                c = o * (1 + rng.gauss(0.0003, 0.015))
                cs.append(Candle(datetime(d.year, d.month, d.day, tzinfo=IST), o, max(o, c) * 1.004, min(o, c) * 0.996, c, 1e5))
                p = c
                d += timedelta(days=1)
            data[f"R{k}"] = cs
        rule = {"lookback": 20, "stop": "pct:5", "target": "2R", "hold": 10, "trend": 0}
        trades = []
        for s, cs in data.items():
            trades += sw.run(s, cs, rule, cfg)["trades"]
        self.assertGreaterEqual(len(trades), 10)
        res = sw.random_baseline(trades, data, rule, cfg, runs=60)
        self.assertEqual(res["trades_compared"], len(trades))
        self.assertLessEqual(res["random_net"]["p05"], res["random_net"]["p95"])
        self.assertFalse(res["beats_random"])  # random walk: breakouts can't beat random days
