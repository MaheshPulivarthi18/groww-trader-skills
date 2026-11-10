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


def build_market(candles_by_symbol: Dict[str, List[Candle]], benchmark: Optional[str]) -> Market:
    by_sym = {s: {c.ts.date(): c for c in cs} for s, cs in candles_by_symbol.items() if cs}
    if benchmark and benchmark in by_sym:
        dates = sorted(by_sym[benchmark])
    else:
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
    return mkt


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
    b = p["benchmark"]
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

    exit_cost = sum(_leg_cost("SELL", m.cf[s][end] or 0, q, charges) for s, q in shares.items())
    final = equity[-1] - exit_cost
    return {"equity": equity, "invested": invested, "final": final, "trades": trades,
            "costs": costs + exit_cost, "traded": traded, "holdings": dict(shares),
            "start": str(m.dates[start]), "end": str(m.dates[end])}


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
    out = {"strategy": metrics(m, sim, start, end, capital, rf), "last_holdings": sim["holdings"]}
    b = p.get("benchmark")
    if b and b in m.c:
        bs = simulate(m, lambda i: {b: 1.0}, [start], start, end, c, capital)
        out["benchmark"] = metrics(m, bs, start, end, capital, rf)
        sc, bc = out["strategy"]["total_return_pct"], out["benchmark"]["total_return_pct"]
        out["excess_total_pct"] = round(sc - bc, 2)
        if out["strategy"]["cagr_pct"] is not None and out["benchmark"]["cagr_pct"] is not None:
            out["excess_cagr_pct"] = round(out["strategy"]["cagr_pct"] - out["benchmark"]["cagr_pct"], 2)
    out["trades_detail"] = sim["trades"]
    return out


def split(m: Market, p: Dict[str, Any], train_frac: float):
    w = warmup(p)
    last = len(m.dates) - 1
    if last - w < 120:
        raise ValueError(f"only {last - w + 1} days after the {w}-day warm-up; fetch more daily history "
                         "(gtrade.py fetch --universe ... --interval 1440 --days 2500)")
    cut = w + int((last - w) * train_frac)
    return w, cut, last


def evaluate(m: Market, p: Dict[str, Any], cfg: Dict[str, Any], train_frac: float = 0.6,
             capital: float = 100000) -> Dict[str, Any]:
    w, cut, last = split(m, p, train_frac)
    return {"params": {k: v for k, v in p.items() if k not in ("universe",)},
            "train": run_period(m, p, cfg, w, cut - 1, capital),
            "test": run_period(m, p, cfg, cut, last, capital),
            "full": run_period(m, p, cfg, w, last, capital)}


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
    if "excess_total_pct" not in tr:
        return "No benchmark data, so nothing to compare against. Fetch the benchmark (e.g. NIFTYBEES)."
    if tr["excess_total_pct"] <= 0:
        return "No variation beat simply holding the benchmark on the train period, after costs."
    if te["excess_total_pct"] <= 0:
        return ("The pick beat the benchmark on the train period but not on the unseen test period: "
                "most likely luck or a regime that ended. Holding the index would have done as well.")
    return (f"The pick beat the benchmark on both periods ({held} of the top {shown} held up on test). "
            "Worth tracking on paper for a few months. Not proof: survivorship bias flatters these "
            "results, the test period is short, and the edge may not last.")
