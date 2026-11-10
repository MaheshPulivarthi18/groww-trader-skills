import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from groww_trader import portfolio as pf  # noqa: E402
from groww_trader import universe  # noqa: E402
from groww_trader.config import load_config  # noqa: E402
from groww_trader.market import IST, Candle  # noqa: E402


def series(daily_growth, n=400, start=100.0, jumps=None):
    """Weekday candles with steady growth; jumps = {index: factor} applied at that day's open."""
    out, p, d = [], start, date(2024, 1, 1)
    for k in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        o = p * (jumps or {}).get(k, 1.0)
        c = o * (1 + daily_growth)
        out.append(Candle(datetime(d.year, d.month, d.day, tzinfo=IST), round(o, 4), round(max(o, c), 4),
                          round(min(o, c), 4), round(c, 4), 1e5))
        p = c
        d += timedelta(days=1)
    return out


class Engine(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config("/nonexistent")
        self.data = {"FAST": series(0.002), "MID": series(0.001), "SLOW": series(0.0), "DOWN": series(-0.001),
                     "IDX": series(0.0008)}
        self.m = pf.build_market(self.data, "IDX")
        self.base = {"strategy": "momentum", "universe": ["FAST", "MID", "SLOW", "DOWN"], "benchmark": "IDX",
                     "lookback": 100, "skip": 0, "top": 1, "weight": "equal", "regime": "off"}

    def test_momentum_holds_the_strongest_and_skips_negatives(self):
        w = pf.momentum(self.m, 200, self.base)
        self.assertEqual(w, {"FAST": 1.0})
        w = pf.momentum(self.m, 200, {**self.base, "top": 4})
        self.assertNotIn("DOWN", w)             # negative momentum never qualifies
        self.assertNotIn("SLOW", w)             # zero isn't positive
        self.assertAlmostEqual(sum(w.values()), 1.0)

    def test_no_lookahead_jump_on_next_open_is_not_seen(self):
        data = dict(self.data)
        data["JUMP"] = series(0.0, jumps={201: 3.0})  # flat, then triples at day 201's open
        m = pf.build_market(data, "IDX")
        p = {**self.base, "universe": ["FAST", "JUMP"]}
        self.assertEqual(pf.momentum(m, 200, p), {"FAST": 1.0})
        self.assertEqual(pf.ret(m, "JUMP", 200, 100), 0.0)  # flat up to day 200
        self.assertGreater(pf.ret(m, "JUMP", 201, 100), 1.5)  # the jump only shows from day 201

    def test_buy_and_hold_benchmark_matches_price_growth_minus_costs(self):
        r = pf.run_period(self.m, {**self.base, "strategy": "momentum"}, self.cfg, 120, 399, 100000)
        b = r["benchmark"]
        growth = self.m.cf["IDX"][399] / self.m.o["IDX"][121] - 1
        self.assertAlmostEqual(b["total_return_pct"] / 100, growth, delta=0.01)  # costs + whole shares
        self.assertLess(b["total_return_pct"] / 100, growth)
        self.assertEqual(b["trades"], 1)

    def test_costs_are_charged_on_every_trade(self):
        r = pf.run_period(self.m, self.base, self.cfg, 120, 399, 100000)
        s = r["strategy"]
        self.assertGreater(s["costs"], 0)
        # holding FAST the whole time: close to its growth, below it by costs
        growth = self.m.cf["FAST"][399] / self.m.o["FAST"][121] - 1
        self.assertLess(s["total_return_pct"] / 100, growth)
        self.assertGreater(s["total_return_pct"] / 100, growth - 0.02)

    def test_regime_filter_goes_to_cash(self):
        data = dict(self.data)
        data["IDX"] = series(-0.002)  # index in a downtrend: below its average
        m = pf.build_market(data, "IDX")
        p = {**self.base, "regime": "cash", "sma": 50}
        self.assertEqual(pf.momentum(m, 200, p), {})
        r = pf.run_period(m, p, self.cfg, 120, 399, 100000)
        self.assertEqual(r["strategy"]["trades"], 0)
        self.assertEqual(r["strategy"]["total_return_pct"], 0.0)

    def test_dual_momentum_and_lowvol(self):
        self.assertEqual(pf.dualmom(self.m, 200, {"assets": ["MID", "SLOW"], "lookback": 100}), {"MID": 1.0})
        self.assertEqual(pf.dualmom(self.m, 200, {"assets": ["DOWN"], "lookback": 100}), {})
        w = pf.lowvol(self.m, 300, {"universe": ["FAST", "MID"], "lookback": 100, "top": 1})
        self.assertEqual(len(w), 1)

    def test_rebalance_days_monthly_and_split(self):
        days = pf.rebalance_days(self.m, 0, 399, "monthly")
        months = {(self.m.dates[i + 1].year, self.m.dates[i + 1].month) for i in days[1:]}
        self.assertEqual(len(months), len(days) - 1)  # one decision per month change
        w, cut, last = pf.split(self.m, self.base, 0.6)
        self.assertLess(w, cut)
        self.assertEqual(last, 399)

    def test_sweep_verdict_vs_benchmark(self):
        res = pf.sweep(self.m, self.base, [{"strategy": "momentum", "lookback": 100, "skip": 0, "top": 1,
                                            "regime": "off", "weight": "equal"}], self.cfg)
        self.assertEqual(res["variants_tested"], 1)
        self.assertIn("both periods", res["verdict"])  # FAST beats a slower index in both halves
        self.assertEqual(len(pf.grid("momentum")), 24)


class Universe(unittest.TestCase):
    def test_parse_nse_csv_and_text(self):
        csv_text = ("﻿Company Name,Industry,Symbol,Series,ISIN Code\n"
                    "Reliance Industries Ltd.,Oil,RELIANCE,EQ,INE002A01018\nTata Consultancy,IT,TCS,EQ,INE467B01029\n")
        self.assertEqual(universe.parse_symbols(csv_text), ["RELIANCE", "TCS"])
        self.assertEqual(universe.parse_symbols("sbin\n# note\nINFY\nsbin\n"), ["SBIN", "INFY"])
        self.assertEqual(universe.load("sbin, infy")[0], ["SBIN", "INFY"])


if __name__ == "__main__":
    unittest.main()


class Adjustments(unittest.TestCase):
    def test_split_bonus_and_demerger_detection(self):
        from groww_trader import adjust
        s = series(0.001, n=60)
        # a 1:10 split on day 20 (price /10 with a +1% move) and a demerger-like drop on day 40
        s = [Candle(c.ts, c.open / 10, c.high / 10, c.low / 10, c.close / 10, c.volume) if 20 <= k else c
             for k, c in enumerate(s)]
        s = [Candle(c.ts, c.open / 1.75, c.high / 1.75, c.low / 1.75, c.close / 1.75, c.volume) if 40 <= k else c
             for k, c in enumerate(s)]
        ev = adjust.detect("X", s)
        self.assertEqual([e["kind"] for e in ev], ["split/bonus", "other"])
        self.assertEqual(ev[0]["factor"], 10.0)
        self.assertAlmostEqual(ev[1]["factor"], 1.75, delta=0.01)
        adj = adjust.apply(s, ev)
        rets = [b.close / a.close - 1 for a, b in zip(adj, adj[1:])]
        self.assertLess(max(abs(r) for r in rets), 0.01)  # no fake crashes left
        self.assertAlmostEqual(adj[-1].close, s[-1].close)  # latest prices unchanged

    def test_real_moves_are_left_alone(self):
        from groww_trader import adjust
        s = series(0.0, n=10, jumps={5: 0.75})  # a genuine -25% day
        self.assertEqual(adjust.detect("X", s), [])


class Benchmarks(unittest.TestCase):
    def test_short_etf_history_falls_back_to_universe_index(self):
        cfg = load_config("/nonexistent")
        data = {"A": series(0.001), "B": series(0.0005), "IDX": series(0.0008)[250:]}  # ETF starts late
        m = pf.build_market(data, "IDX", ew_universe=["A", "B"])
        self.assertEqual(len(m.dates), 400)                  # calendar no longer cut to the ETF's dates
        p = {"strategy": "momentum", "universe": ["A", "B"], "benchmark": "IDX", "lookback": 100, "skip": 0,
             "top": 1, "regime": "cash", "sma": 50}
        self.assertEqual(pf.regime_symbol(m, p), pf.EQW)
        r = pf.run_period(m, p, cfg, 120, 240, 100000)
        self.assertEqual(r["benchmark_name"], "universe equal-weight")
        self.assertNotIn("etf", r)
        r2 = pf.run_period(m, p, cfg, 260, 399, 100000)
        self.assertEqual(r2["benchmark_name"], "IDX")         # ETF used once it covers the period
        # equal-weight index ~ average of A and B growth, no costs
        ew = r["universe_ew"]["total_return_pct"] / 100
        ga = m.cf["A"][240] / m.cf["A"][120] - 1
        gb = m.cf["B"][240] / m.cf["B"][120] - 1
        self.assertTrue(min(ga, gb) - 0.01 < ew < max(ga, gb) + 0.01)
