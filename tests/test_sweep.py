import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import random_days  # noqa: E402
from groww_trader import sweep as sw  # noqa: E402
from groww_trader.config import load_config  # noqa: E402


def cfg():
    return load_config("/nonexistent")


class Sweep(unittest.TestCase):
    def setUp(self):
        self.data = {s: random_days(date(2026, 8, 3), 30, seed=30 + i, price=200 + 50 * i)
                     for i, s in enumerate(("AAA", "BBB"))}

    def test_variants_respect_setup_stops(self):
        vs = sw.variants(["orb", "pdh_breakout"], ["or_mid", "level", "pct:1"], ["1R", "2R"], [15, 30])
        orb = [v for v in vs if v["setup"] == "orb"]
        pdh = [v for v in vs if v["setup"] == "pdh_breakout"]
        self.assertEqual({v["stop"] for v in orb}, {"or_mid", "pct:1"})
        self.assertEqual({v["stop"] for v in pdh}, {"level", "pct:1"})
        self.assertEqual(len(orb), 2 * 2 * 2)
        self.assertTrue(all(v["range_min"] is None for v in pdh))

    def test_train_and_test_never_overlap(self):
        vs = sw.variants(["orb"], ["pct:1"], ["1.5R"], None)
        res = sw.sweep(self.data, cfg(), 5, vs, train_frac=0.6, min_trades=0, top=3)
        cut = date.fromisoformat(res["split"]["test_from"])
        row = res["all"][0]
        self.assertEqual(res["variants_tested"], 1)
        # re-run to inspect the trades themselves
        c = sw._apply(cfg(), vs[0])
        from groww_trader.backtest import run
        for sym, candles in self.data.items():
            tr = run(sym, candles, "orb", c, 5, to_day=cut - timedelta(days=1))
            te = run(sym, candles, "orb", c, 5, from_day=cut)
            self.assertTrue(all(date.fromisoformat(t["day"]) < cut for t in tr["trades"]))
            self.assertTrue(all(date.fromisoformat(t["day"]) >= cut for t in te["trades"]))
        self.assertIn("trades", row["train"])

    def test_too_little_data(self):
        short = {"AAA": random_days(date(2026, 8, 3), 5, seed=1)}
        with self.assertRaises(ValueError):
            sw.split_day(short, 0.6)

    def test_verdicts(self):
        mk = lambda trn, tst, n=20: {"train": {"net_total": trn, "trades": 20}, "test": {"net_total": tst, "trades": n}}
        self.assertIn("No edge", sw.verdict(mk(-5, 10), 0, 5))
        self.assertIn("LOST", sw.verdict(mk(50, -10), 0, 5))
        self.assertIn("too few", sw.verdict(mk(50, 10, n=3), 0, 5))
        self.assertIn("both periods", sw.verdict(mk(50, 10), 2, 5))
        self.assertIn("enough trades", sw.verdict(None, 0, 0))


if __name__ == "__main__":
    unittest.main()
