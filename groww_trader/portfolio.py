"""Portfolio strategies on daily candles: rank a universe, hold the best,
rebalance monthly (or weekly), and compare with simply holding the index.

Strategies
  momentum  Hold the `top` stocks with the highest return over `lookback`
            trading days, skipping the most recent `skip` days (the classic
            "12-1" momentum). Only stocks with a positive score qualify.
  lowvol    Hold the `top` stocks with the lowest volatility of daily returns
            over `lookback` days.
  dualmom   Each period, hold the one asset from `assets` (e.g. index and gold
            ETFs) with the best `lookback` return, or cash if none is positive.

Options for all
  weight    "equal", or "invvol": weights proportional to 1 / 60-day volatility
  regime    "off", or "cash": hold cash while the benchmark closes below its
            `sma`-day average (trend / bear-market filter)
  band      skip resizing a holding whose share count would change by less
            than this fraction (reduces churn and costs)

Execution model (no lookahead)
  * scores use closes up to the decision day only
  * orders fill at the NEXT trading day's open, plus slippage against you
  * delivery (CNC) charges on every buy and sell, DP charge on sells
  * whole shares only; idle cash earns `cash_yield_pct` a year (default 0)
  * final value is after selling everything (exit charges included)

The benchmark (default NIFTYBEES) is bought once with the same costs and held.
"""

from __future__ import annotations

import copy
import itertools
import math
import random
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Sequence

from .costs import round_trip
from .market import Candle

TRADING_DAYS = 252


# ------------------------------------------------------------------ data

@dataclass
class Market:
    dates: List[date]
    o: Dict[str, List[Optional[float]]] = field(default_factory=dict)   # open, None if no bar that day
    c: Dict[str, List[Optional[float]]] = field(default_factory=dict)   # close, None if no bar
    cf: Dict[str, List[Optional[float]]] = field(default_factory=dict)  # close carried forward

    @property
    def symbols(self) -> List[str]:
        return list(self.c)


EQW = "_EQW"  # equal-weight index of the universe, built from the data


def build_market(candles_by_symbol: Dict[str, List[Candle]], benchmark: Optional[str] = None,
                 ew_universe: Optional[List[str]] = None) -> Market:
    """Calendar = every date any symbol traded. With `ew_universe`, also builds
    `_EQW`: an index whose daily return is the average return of the
    universe's stocks that traded on both days (no costs, rebalanced daily).
    It stands in for the market where the benchmark ETF's history is short."""
    by_sym = {s: {c.ts.date(): c for c in cs} for s, cs in candles_by_symbol.items() if cs}
    dates = sorted({d for m in by_sym.values() for d in m})
    mkt = Market(dates=dates)
    for s, m in by_sym.items():
        o, c, cf, last = [], [], [], None
        for d in dates:
            bar = m.get(d)
            o.append(bar.open if bar else None)
            c.append(bar.close if bar else None)
            if bar:
                last = bar.close
            cf.append(last)
        mkt.o[s], mkt.c[s], mkt.cf[s] = o, c, cf
    members = [s for s in (ew_universe or []) if s in mkt.c]
    if members:
        v, o, c = 100.0, [], []
        for i in range(len(dates)):
            rs = [mkt.c[s][i] / mkt.c[s][i - 1] - 1 for s in members
                  if i > 0 and mkt.c[s][i] is not None and mkt.c[s][i - 1]]
            prev = v
            if rs:
                v *= 1 + sum(rs) / len(rs)
            o.append(prev if i > 0 else v)
            c.append(v)
        mkt.o[EQW], mkt.c[EQW], mkt.cf[EQW] = o, c, list(c)
    return mkt


def covers(m: Market, s: Optional[str], i: int) -> bool:
    return bool(s) and s in m.cf and m.cf[s][i] is not None


# ------------------------------------------------------------------ indicators (use data up to i only)

def ret(m: Market, s: str, i: int, lookback: int, skip: int = 0) -> Optional[float]:
    a, b = i - skip, i - skip - lookback
    if b < 0:
        return None
    pa, pb = m.cf[s][a], m.cf[s][b]
    return pa / pb - 1 if pa and pb else None


def vol(m: Market, s: str, i: int, n: int) -> Optional[float]:
    if i - n < 0:
        return None
    px = m.cf[s][i - n:i + 1]
    if any(p is None or p <= 0 for p in px):
        return None
    r = [math.log(px[k] / px[k - 1]) for k in range(1, len(px))]
    return statistics.pstdev(r) * math.sqrt(TRADING_DAYS) if len(r) > 2 else None


def sma(m: Market, s: str, i: int, n: int) -> Optional[float]:
    if i - n + 1 < 0:
        return None
    px = m.cf[s][i - n + 1:i + 1]
    return sum(px) / n if all(p is not None for p in px) else None


def risk_on(m: Market, i: int, p: Dict[str, Any]) -> bool:
    if p.get("regime", "off") != "cash":
        return True
    b = p.get("regime_symbol") or p["benchmark"]
    avg = sma(m, b, i, int(p.get("sma", 200)))
    return avg is None or (m.cf[b][i] or 0) > avg


def _weights(m: Market, picks: List[str], i: int, how: str) -> Dict[str, float]:
    if not picks:
        return {}
    if how == "invvol":
        inv = {s: 1 / v for s in picks if (v := vol(m, s, i, 60))}
        tot = sum(inv.values())
        if tot > 0:
            return {s: w / tot for s, w in inv.items()}
    return {s: 1 / len(picks) for s in picks}


def _tradable(m: Market, s: str, i: int) -> bool:
    return m.c[s][i] is not None


# ------------------------------------------------------------------ strategies: (market, day, params) -> weights

def momentum(m: Market, i: int, p: Dict[str, Any]) -> Dict[str, float]:
    if not risk_on(m, i, p):
        return {}
    lb, skip = int(p.get("lookback", 252)), int(p.get("skip", 21))
    scores = {s: r for s in p["universe"] if s in m.c and _tradable(m, s, i)
              and (r := ret(m, s, i, lb, skip)) is not None and r > float(p.get("min_score", 0))}
    picks = sorted(scores, key=scores.get, reverse=True)[: int(p.get("top", 10))]
    return _weights(m, picks, i, p.get("weight", "equal"))


def lowvol(m: Market, i: int, p: Dict[str, Any]) -> Dict[str, float]:
    if not risk_on(m, i, p):
        return {}
    lb = int(p.get("lookback", 252))
    vols = {s: v for s in p["universe"] if s in m.c and _tradable(m, s, i) and (v := vol(m, s, i, lb))}
    picks = sorted(vols, key=vols.get)[: int(p.get("top", 10))]
    return _weights(m, picks, i, p.get("weight", "equal"))


def dualmom(m: Market, i: int, p: Dict[str, Any]) -> Dict[str, float]:
    lb = int(p.get("lookback", 252))
    rets = {a: r for a in p["assets"] if a in m.c and _tradable(m, a, i) and (r := ret(m, a, i, lb)) is not None}
    if not rets:
        return {}
    best = max(rets, key=rets.get)
    return {best: 1.0} if rets[best] > 0 else {}


STRATEGIES: Dict[str, Callable] = {"momentum": momentum, "lowvol": lowvol, "dualmom": dualmom}


def warmup(p: Dict[str, Any]) -> int:
    lb = int(p.get("lookback", 252)) + int(p.get("skip", 21 if p.get("strategy") == "momentum" else 0))
    need = [lb + 1, 61]
    if p.get("regime") == "cash":
        need.append(int(p.get("sma", 200)))
    return max(need)


def rebalance_days(m: Market, start: int, end: int, every: str) -> List[int]:
    key = (lambda d: d.isocalendar()[:2]) if every == "weekly" else (lambda d: (d.year, d.month))
    out = [start]
    for i in range(start + 1, end):
        if key(m.dates[i + 1]) != key(m.dates[i]):
            out.append(i)
    return sorted(set(out))


# ------------------------------------------------------------------ simulation

def _leg_cost(side: str, price: float, qty: int, charges: Dict[str, Any]) -> float:
    if qty <= 0:
        return 0.0
    if side == "BUY":
        return round_trip(price, 0, qty, charges, "CNC")["total"]
    return round_trip(0, price, qty, charges, "CNC")["total"]


def simulate(m: Market, decide: Callable[[int], Dict[str, float]], days: Sequence[int], start: int, end: int,
             cfg: Dict[str, Any], capital: float) -> Dict[str, Any]:
    charges = cfg["charges"]
    slip = cfg.get("slippage_pct", 0.0) / 100
    band = float(cfg.get("_band", 0.2))
    daily_cash = (1 + float(cfg.get("_cash_yield_pct", 0)) / 100) ** (1 / TRADING_DAYS) - 1
    cash, shares = float(capital), {}
    lots: Dict[str, List[List[Any]]] = {}      # FIFO: [qty, cost per share incl. buy charges, buy date]
    realised: List[Any] = []                   # (sell date, gain after charges, days held)

    def _realise(s_, q_, net_ps, d_):
        while q_ > 0 and lots.get(s_):
            lot = lots[s_][0]
            k = min(q_, lot[0])
            realised.append((d_, k * (net_ps - lot[1]), (d_ - lot[2]).days))
            lot[0] -= k
            q_ -= k
            if lot[0] == 0:
                lots[s_].pop(0)

    pending: Optional[Dict[str, float]] = None
    decide_on = set(days)
    equity, invested, trades = [], [], []
    costs = traded = 0.0

    for i in range(start, end + 1):
        if pending is not None:  # fill yesterday's decision at today's open
            px = {s: (m.o[s][i] if m.o[s][i] is not None else m.cf[s][i - 1]) for s in set(shares) | set(pending)}
            eq_open = cash + sum(q * (px[s] or 0) for s, q in shares.items())
            want: Dict[str, int] = {}
            for s, w in pending.items():
                if m.o[s][i] is None:
                    continue  # no bar today: can't buy it
                want[s] = int(eq_open * w * 0.995 // (m.o[s][i] * (1 + slip)))
            for s, cur in list(shares.items()):  # keep holdings we can't trade today
                if m.o[s][i] is None:
                    want[s] = cur
                elif s in want and cur and abs(want[s] - cur) / cur < band:
                    want[s] = cur
            for s, cur in list(shares.items()):  # sells first
                q = cur - want.get(s, 0)
                if q > 0:
                    p_ = round(m.o[s][i] * (1 - slip), 2)
                    c_ = _leg_cost("SELL", p_, q, charges)
                    cash += q * p_ - c_
                    costs += c_
                    _realise(s, q, (q * p_ - c_) / q, m.dates[i])
                    traded += q * p_
                    trades.append({"date": str(m.dates[i]), "symbol": s, "side": "SELL", "qty": q, "price": p_, "cost": c_})
                    shares[s] = cur - q
                    if shares[s] == 0:
                        del shares[s]
            for s, tgt in sorted(want.items(), key=lambda kv: -pending.get(kv[0], 0)):  # then buys
                q = tgt - shares.get(s, 0)
                if q <= 0:
                    continue
                p_ = round(m.o[s][i] * (1 + slip), 2)
                while q > 0 and q * p_ + _leg_cost("BUY", p_, q, charges) > cash:
                    q -= max(1, q // 20)
                if q <= 0:
                    continue
                c_ = _leg_cost("BUY", p_, q, charges)
                cash -= q * p_ + c_
                costs += c_
                lots.setdefault(s, []).append([q, (q * p_ + c_) / q, m.dates[i]])
                traded += q * p_
                trades.append({"date": str(m.dates[i]), "symbol": s, "side": "BUY", "qty": q, "price": p_, "cost": c_})
                shares[s] = shares.get(s, 0) + q
            pending = None
        if cash > 0:
            cash *= 1 + daily_cash
        val_held = sum(q * (m.cf[s][i] or 0) for s, q in shares.items())
        equity.append(cash + val_held)
        invested.append(val_held)
        if i in decide_on and i < end:
            pending = decide(i)

    exit_cost = 0.0
    for s, q in shares.items():  # value at the end = selling everything
        px_ = m.cf[s][end] or 0
        c_ = _leg_cost("SELL", px_, q, charges)
        exit_cost += c_
        if q:
            _realise(s, q, (q * px_ - c_) / q, m.dates[end])
    final = equity[-1] - exit_cost
    return {"equity": equity, "invested": invested, "final": final, "trades": trades,
            "costs": costs + exit_cost, "traded": traded, "holdings": dict(shares), "realised": realised,
            "start": str(m.dates[start]), "end": str(m.dates[end])}


def _after_tax(sim: Dict[str, Any], capital: float, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Capital gains tax on everything realised, including the final sale.
    Paid at the end in this model (in reality, each year), which slightly
    flatters high-turnover strategies."""
    from .tax import capital_gains_tax
    t = capital_gains_tax(sim.get("realised", []), cfg)
    after = sim["final"] - t["total_tax"]
    st = sum(g for _, g, h in sim.get("realised", []) if h <= 365)
    return {"tax": t["total_tax"], "short_term_gains": round(st, 2),
            "after_tax_return_pct": round(100 * (after / capital - 1), 2)}


def metrics(m: Market, sim: Dict[str, Any], start: int, end: int, capital: float, rf_pct: float) -> Dict[str, Any]:
    eq = sim["equity"]
    years = max((m.dates[end] - m.dates[start]).days / 365.25, 1e-9)
    total = sim["final"] / capital - 1
    rets = [eq[k] / eq[k - 1] - 1 for k in range(1, len(eq)) if eq[k - 1] > 0]
    sd = statistics.pstdev(rets) * math.sqrt(TRADING_DAYS) if len(rets) > 2 else None
    mean = statistics.mean(rets) * TRADING_DAYS if rets else 0.0
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    avg_eq = statistics.mean(eq) if eq else capital
    return {
        "start": sim["start"], "end": sim["end"], "years": round(years, 2),
        "final": round(sim["final"], 2),
        "total_return_pct": round(100 * total, 2),
        "cagr_pct": round(100 * ((1 + total) ** (1 / years) - 1), 2) if years >= 0.25 and total > -1 else None,
        "max_drawdown_pct": round(100 * mdd, 2),
        "volatility_pct": round(100 * sd, 2) if sd else None,
        "sharpe": round((mean - rf_pct / 100) / sd, 2) if sd else None,
        "trades": len(sim["trades"]),
        "costs": round(sim["costs"], 2),
        "turnover_per_year": round(sim["traded"] / avg_eq / years, 2) if avg_eq else None,
        "time_invested_pct": round(100 * sum(1 for v, e in zip(sim["invested"], eq) if e and v / e > 0.5) / len(eq), 1),
    }


def run_period(m: Market, p: Dict[str, Any], cfg: Dict[str, Any], start: int, end: int,
               capital: float) -> Dict[str, Any]:
    c = copy.deepcopy(cfg)
    c["_band"] = p.get("band", 0.2)
    c["_cash_yield_pct"] = p.get("cash_yield_pct", 0)
    rf = float(p.get("rf_pct", 6.5))
    strat = STRATEGIES[p["strategy"]]
    sim = simulate(m, lambda i: strat(m, i, p), rebalance_days(m, start, end, p.get("rebalance", "monthly")),
                   start, end, c, capital)
    out = {"strategy": {**metrics(m, sim, start, end, capital, rf), **_after_tax(sim, capital, c)},
           "last_holdings": sim["holdings"]}
    b = p.get("benchmark")
    if covers(m, b, start):  # the ETF, bought once with real costs
        bs = simulate(m, lambda i: {b: 1.0}, [start], start, end, c, capital)
        out["etf"] = {**metrics(m, bs, start, end, capital, rf), **_after_tax(bs, capital, c)}
    if EQW in m.c:  # the universe itself, equal weight, no costs (a generous yardstick)
        free = copy.deepcopy(c)
        free["slippage_pct"] = 0.0
        free["charges"] = {**free["charges"], "brokerage_pct": 0, "brokerage_min": 0, "exchange_txn_pct": 0,
                           "sebi_pct": 0, "intraday": {k: 0 for k in free["charges"]["intraday"]},
                           "delivery": {k: 0 for k in free["charges"]["delivery"]}}
        es = simulate(m, lambda i: {EQW: 1.0}, [start], start, end, {**free, "_band": 0}, 1e9)
        out["universe_ew"] = metrics(m, {**es, "final": es["final"] / 1e9 * capital,
                                         "equity": [e / 1e9 * capital for e in es["equity"]]},
                                     start, end, capital, rf)
    # The comparison that counts: the ETF when its history covers the period, else the universe.
    primary = "etf" if "etf" in out else ("universe_ew" if "universe_ew" in out else None)
    if primary:
        out["benchmark"] = out[primary]
        out["benchmark_name"] = b if primary == "etf" else "universe equal-weight"
        sc, bc = out["strategy"]["total_return_pct"], out["benchmark"]["total_return_pct"]
        out["excess_total_pct"] = round(sc - bc, 2)
        if "after_tax_return_pct" in out["benchmark"]:
            out["excess_after_tax_pct"] = round(out["strategy"]["after_tax_return_pct"]
                                                - out["benchmark"]["after_tax_return_pct"], 2)
        if out["strategy"]["cagr_pct"] is not None and out["benchmark"]["cagr_pct"] is not None:
            out["excess_cagr_pct"] = round(out["strategy"]["cagr_pct"] - out["benchmark"]["cagr_pct"], 2)
    out["trades_detail"] = sim["trades"]
    return out


def random_picks(m: Market, p: Dict[str, Any], cfg: Dict[str, Any], start: int, end: int,
                 capital: float, real_total_pct: float, runs: int = 100, seed: int = 13) -> Dict[str, Any]:
    """Does the strategy's choice of stocks beat choosing at random?

    Each run follows the strategy's own schedule and exposure: on every
    rebalance day it holds as many positions as the strategy did (none when
    the strategy or its regime filter was in cash), but picks them at random
    from the eligible pool (stocks with enough history that day), weighted
    the same way, with the same costs and slippage. So only the selection
    differs. Random runs also replace as many names as the strategy does on
    each rebalance, so turnover and costs match too."""
    c = copy.deepcopy(cfg)
    c["_band"] = p.get("band", 0.2)
    c["_cash_yield_pct"] = p.get("cash_yield_pct", 0)
    strat = STRATEGIES[p["strategy"]]
    pool_key = "assets" if p["strategy"] == "dualmom" else "universe"
    lb = int(p.get("lookback", 252))
    days = rebalance_days(m, start, end, p.get("rebalance", "monthly"))
    eligible = lambda s_, i: s_ in m.c and _tradable(m, s_, i) and ret(m, s_, i, lb) is not None
    totals = []
    for r in range(runs):
        rng = random.Random(seed * 1000 + r)
        state = {"real": set(), "held": []}

        def decide(i, rng=rng, state=state):
            real = set(strat(m, i, p))
            entered = len(real - state["real"])          # names the strategy swapped in
            state["real"] = real
            k = len(real)
            held = [x for x in state["held"] if eligible(x, i)]
            keep = rng.sample(held, max(0, min(len(held), k - entered)))
            pool = [x for x in p[pool_key] if eligible(x, i) and x not in keep]
            held = keep + rng.sample(pool, min(k - len(keep), len(pool)))
            state["held"] = held
            return _weights(m, held, i, p.get("weight", "equal")) if held else {}

        sim = simulate(m, decide, days, start, end, c, capital)
        totals.append(100 * (sim["final"] / capital - 1))
    totals.sort()
    pct = lambda q: round(totals[min(runs - 1, int(q * runs))], 2)
    share = sum(1 for t in totals if t >= real_total_pct) / runs
    return {"runs": runs, "seed": seed, "strategy_total_pct": real_total_pct,
            "random_total_pct": {"p05": pct(0.05), "median": pct(0.5), "p95": pct(0.95)},
            "share_of_random_runs_as_good_pct": round(100 * share, 1),
            "beats_random": share <= 0.05,
            "method": "same rebalance days, number of holdings, names replaced per rebalance, weighting, costs and slippage; stocks picked at random"}


def split(m: Market, p: Dict[str, Any], train_frac: float):
    w = warmup(p)
    last = len(m.dates) - 1
    if last - w < 120:
        raise ValueError(f"only {last - w + 1} days after the {w}-day warm-up; fetch more daily history "
                         "(gtrade.py fetch --universe ... --interval 1440 --days 2500)")
    cut = w + int((last - w) * train_frac)
    return w, cut, last


def regime_symbol(m: Market, p: Dict[str, Any]) -> Optional[str]:
    """The benchmark ETF if its history starts with the data, else the
    universe's equal-weight index, so the filter means the same all along."""
    b = p.get("benchmark")
    if covers(m, b, min(len(m.dates) - 1, int(p.get("sma", 200)))):
        return b
    return EQW if EQW in m.c else b


def evaluate(m: Market, p: Dict[str, Any], cfg: Dict[str, Any], train_frac: float = 0.6,
             capital: float = 100000, baseline_runs: int = 0) -> Dict[str, Any]:
    p = {**p, "regime_symbol": regime_symbol(m, p)}
    w, cut, last = split(m, p, train_frac)
    res = {"params": {k: v for k, v in p.items() if k not in ("universe",)},
           "train": run_period(m, p, cfg, w, cut - 1, capital),
           "test": run_period(m, p, cfg, cut, last, capital),
           "full": run_period(m, p, cfg, w, last, capital)}
    if baseline_runs:
        for name, (a, b) in (("train", (w, cut - 1)), ("test", (cut, last))):
            res[name]["vs_random_picks"] = random_picks(
                m, p, cfg, a, b, capital, res[name]["strategy"]["total_return_pct"], runs=baseline_runs)
    res["verdict"] = single_verdict(res)
    return res


def single_verdict(res: Dict[str, Any]) -> str:
    """Plain verdict for one strategy, judged mainly on the later (test) period."""
    te, tr = res["test"], res["train"]
    vr = te.get("vs_random_picks")
    if "excess_total_pct" not in te:
        base = "No benchmark covers the test period, so it can't be judged against the index."
    elif te["excess_total_pct"] <= 0:
        base = (f"Did not beat simply holding {te.get('benchmark_name')} on the later, unseen period "
                f"({te['excess_total_pct']:+.1f} points)" + (", although it did on the earlier one." if tr.get("excess_total_pct", 0) > 0 else "."))
    else:
        base = f"Beat {te.get('benchmark_name')} on the later period by {te['excess_total_pct']:+.1f} points."
    if not vr:
        return base + " Not compared with random picks (use --baseline)."
    if vr["beats_random"]:
        rnd = " Its stock selection beat random picks there too ({}% of random runs did as well).".format(
            vr["share_of_random_runs_as_good_pct"])
    else:
        rnd = (" But random picks with the same schedule did as well in {}% of runs: the selection rule "
               "itself added nothing measurable.").format(vr["share_of_random_runs_as_good_pct"])
    tail = ""
    if "excess_total_pct" in te and te["excess_total_pct"] > 0 and vr["beats_random"]:
        tail = " Worth paper-tracking for months; survivorship bias and a short test period still flatter it."
    return base + rnd + tail


# ------------------------------------------------------------------ sweep

def grid(strategy: str) -> List[Dict[str, Any]]:
    if strategy == "momentum":
        return [{"strategy": "momentum", "lookback": lb, "skip": 21, "top": n, "regime": r, "weight": wt}
                for lb, n, r, wt in itertools.product((126, 252), (5, 10, 20), ("off", "cash"), ("equal", "invvol"))]
    if strategy == "lowvol":
        return [{"strategy": "lowvol", "lookback": 252, "top": n, "regime": r, "weight": "equal"}
                for n, r in itertools.product((10, 20), ("off", "cash"))]
    if strategy == "dualmom":
        return [{"strategy": "dualmom", "lookback": lb} for lb in (126, 252)]
    raise ValueError(f"unknown strategy {strategy!r}")


def sweep(m: Market, base: Dict[str, Any], variants: List[Dict[str, Any]], cfg: Dict[str, Any],
          train_frac: float = 0.6, capital: float = 100000, top: int = 5) -> Dict[str, Any]:
    base = {**base, "regime_symbol": regime_symbol(m, base)}
    # one common split for every variant: the longest warm-up decides it
    w = max(warmup({**base, **v}) for v in variants)
    last = len(m.dates) - 1
    if last - w < 120:
        raise ValueError(f"only {last - w + 1} days after the {w}-day warm-up; fetch more daily history")
    cut = w + int((last - w) * train_frac)
    rows = []
    for v in variants:
        p = {**base, **v}
        tr = run_period(m, p, cfg, w, cut - 1, capital)
        te = run_period(m, p, cfg, cut, last, capital)
        tr.pop("trades_detail", None)
        te.pop("trades_detail", None)
        rows.append({"rule": v, "train": tr, "test": te})
    key = lambda r: r["train"].get("excess_total_pct", r["train"]["strategy"]["total_return_pct"])
    ranked = sorted(rows, key=key, reverse=True)
    best = ranked[0] if ranked else None
    beat_train = sum(1 for r in rows if key(r) > 0)
    held = sum(1 for r in ranked[:top] if r["test"].get("excess_total_pct", -1) > 0)
    return {"split": {"train": [str(m.dates[w]), str(m.dates[cut - 1])], "test": [str(m.dates[cut]), str(m.dates[last])]},
            "variants_tested": len(rows), "beat_benchmark_on_train": beat_train,
            "top": ranked[:top], "pick": best, "verdict": verdict(best, held, min(top, len(ranked))), "all": rows}


def verdict(best, held: int, shown: int) -> str:
    if not best:
        return "Nothing to judge."
    tr, te = best["train"], best["test"]
    if "excess_total_pct" not in tr or "excess_total_pct" not in te:
        return "No benchmark covers these dates, so nothing to compare against."
    if tr["excess_total_pct"] <= 0:
        return "No variation beat simply holding the benchmark on the train period, after costs."
    if te["excess_total_pct"] <= 0:
        return ("The pick beat the benchmark on the train period but not on the unseen test period: "
                "most likely luck or a regime that ended. Holding the index would have done as well.")
    return (f"The pick beat the benchmark on both periods ({held} of the top {shown} held up on test). "
            "Worth tracking on paper for a few months. Not proof: survivorship bias flatters these "
            "results, the test period is short, and the edge may not last.")


def walk_forward(m: Market, base: Dict[str, Any], variants: List[Dict[str, Any]], cfg: Dict[str, Any],
                 train_days: int = 504, test_days: int = 252, capital: float = 100000) -> Dict[str, Any]:
    """Choose the best variation on `train_days`, hold it for the next
    `test_days`, roll forward, and chain the unseen periods together. That is
    what following the search would actually have earned."""
    base = {**base, "regime_symbol": regime_symbol(m, base)}
    w = max(warmup({**base, **v}) for v in variants)
    last = len(m.dates) - 1
    if last - w < train_days + test_days:
        raise ValueError(f"only {last - w + 1} days after the {w}-day warm-up; walk-forward needs "
                         f"{train_days + test_days} (fetch more history or use smaller windows)")
    folds = []
    start = w
    key = lambda r: r.get("excess_total_pct", r["strategy"]["total_return_pct"])
    while start + train_days + test_days - 1 <= last:
        a, b = start, start + train_days - 1
        c_, d_ = b + 1, min(last, b + test_days)
        scored = []
        for v in variants:
            r = run_period(m, {**base, **v}, cfg, a, b, capital)
            scored.append((key(r), v))
        best_score, v = max(scored, key=lambda x: x[0])
        te = run_period(m, {**base, **v}, cfg, c_, d_, capital)
        folds.append({"train": [str(m.dates[a]), str(m.dates[b])], "test": [str(m.dates[c_]), str(m.dates[d_])],
                      "pick": v, "train_excess_pct": round(best_score, 2),
                      "test_return_pct": te["strategy"]["total_return_pct"],
                      "test_benchmark_pct": te.get("benchmark", {}).get("total_return_pct"),
                      "benchmark_name": te.get("benchmark_name")})
        start += test_days
    grow = lambda xs: round(100 * (math.prod(1 + x / 100 for x in xs) - 1), 2)
    strat = grow([f["test_return_pct"] for f in folds])
    have_b = all(f["test_benchmark_pct"] is not None for f in folds)
    bench = grow([f["test_benchmark_pct"] for f in folds]) if have_b else None
    beat = sum(1 for f in folds if f["test_benchmark_pct"] is not None and f["test_return_pct"] > f["test_benchmark_pct"])
    if not folds:
        v_ = "Not enough history for a single window."
    elif bench is None:
        v_ = "No benchmark covers every window, so it can't be judged against the index."
    elif strat > bench:
        v_ = (f"Following the search beat the benchmark out of sample ({strat:+.1f}% vs {bench:+.1f}%, "
              f"{beat} of {len(folds)} windows). Worth paper-tracking; survivorship bias still flatters it.")
    else:
        v_ = (f"Following the search did NOT beat the benchmark out of sample ({strat:+.1f}% vs {bench:+.1f}%, "
              f"{beat} of {len(folds)} windows ahead). Holding the index would have done as well or better.")
    return {"windows": len(folds), "train_days": train_days, "test_days": test_days,
            "variants_tried": len(variants), "folds": folds,
            "chained_test_return_pct": strat, "chained_benchmark_pct": bench,
            "windows_beating_benchmark": beat, "verdict": v_}
