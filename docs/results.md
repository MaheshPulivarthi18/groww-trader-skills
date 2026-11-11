# What we found: November 2026

The first real research run with these tools, on real Groww data, after Indian charges. We publish it because the result is the useful part: **none of the rules we tried has an edge after costs.** If you test your own ideas with this project, this is the bar they need to clear, and the method below is how to test them without fooling yourself.

Not financial advice. Past results, and especially past *losses*, say nothing certain about the future.

## Setup

| | |
|---|---|
| Stocks | RELIANCE, HDFCBANK, ICICIBANK, INFY, TCS, SBIN, AXISBANK, KOTAKBANK, LT, BHARTIARTL (NSE) |
| Intraday data | 5-minute candles, 10 Nov 2025 to 9 Nov 2026 (about 250 sessions per stock) |
| Daily data | 6 Nov 2023 to 9 Nov 2026 (747 sessions per stock) |
| Capital and risk | ₹1,00,000; ₹500 max loss per trade; max 25% of capital per position |
| Costs | Groww's published equity pricing: brokerage 0.1% capped at ₹20 per order; STT, exchange and SEBI fees, stamp duty, GST; DP charge on delivery sells |
| Fills | next bar's open + 0.03% slippage; targets need a trade-through; stops pay 0.05% extra slippage |
| Method | `sweep` / `swing`: choose on the earlier 60% of sessions, report the later 40% that played no part in the choice |

## Intraday (MIS): no edge

`gtrade.py sweep --source csv --shorts`: 68 rule variations (opening-range breakout, previous-day high/low breakout, failed-breakout fade, VWAP reclaim; several stops and targets each), longs and shorts, across all 10 stocks.

Train up to 17 Jun 2026, test from 18 Jun 2026.

| best variations (ranked on train) | train trades | train net ₹ | test trades | test net ₹ |
|---|---:|---:|---:|---:|
| pdh_breakout, stop 0.5%, target 1.5R | 710 | −45,727 | 507 | −33,907 |
| pdh_breakout, stop 0.5%, target 2R | 710 | −46,628 | 507 | −30,897 |
| pdh_breakout, stop ATR×1.5, target 2R | 710 | −47,898 | 507 | −31,954 |
| pdh_breakout, stop 1%, target 1R | 710 | −48,063 | 507 | −30,053 |
| pdh_breakout, stop ATR×1.5, target 1.5R | 710 | −48,365 | 507 | −33,691 |

**0 of 68** variations made money on the train period.

How to read it: the best rule lost about **₹64 per trade**, and charges on a ~₹25,000 intraday round trip are about **₹56**. Before costs these rules are roughly break-even, close to random entries; costs turn them into steady losers. With over 1,200 trades this is not bad luck.

An earlier 60-day test of the same families pointed the same way, and single-stock backtests showed the mechanism: most breakouts hit the stop or ran out of time, few reached the target.

### Against random entry timing (₹20,000 account)

`gtrade.py backtest --days 365 --source csv --baseline 500`, the whole watchlist as one account: ₹20,000 capital, ₹200 max loss a trade, ₹400 a day, 1 position at a time, 2 trades a day, opening range at least 1%. Each real trade was replayed 500 times at a random entry time on the same stock and day, with the same stop %, target, fills and charges.

| rule | trades | before charges ₹ | charges ₹ | net ₹ | random runs as good or better |
|---|---:|---:|---:|---:|---:|
| `orb`, stop mid-range, 1.5R | 182 | −312 | 4,536 | −4,848 (−24%) | 98.2% (worse than random) |
| `orb_fade`, stop beyond the failed move, 1.5R | 373 | −4,034 | 9,352 | −13,386 (−67%) | 62% (same as random) |

Neither entry beats random timing. Random long entries made about ₹6 a trade before charges (the market drifted up over the year) against about ₹25 of charges, so even random buying lost. Buying breakouts did slightly worse than random, but fading them wasn't better than random either, so this isn't a tradeable reversal; it is most likely time of day (breakout entries cluster in the choppy first hour). For intraday trades on these stocks, charges, not entry timing, decide the result. `gtrade.py costs` shows the break-even move for any trade size.

## Swing (delivery, CNC): closest, still negative

`gtrade.py swing --source csv`: 72 variations of an N-day-high breakout (20 or 55 days; stop 3%, 5% or ATR×2; target 2R, 3R or none; hold up to 10 or 20 days; with or without a 50-day average filter), longs only.

Train up to 22 Aug 2025, test from 25 Aug 2025.

| best variations (ranked on train) | train trades | train net ₹ | test trades | test net ₹ |
|---|---:|---:|---:|---:|
| 20-day high, stop 5%, target 3R, hold 20d | 97 | −538 | 65 | −2,529 |
| 20-day high, stop ATR×2, target 3R, hold 20d | 98 | −1,647 | 68 | −3,933 |
| 20-day high, stop 5%, target 2R, hold 20d | 101 | −1,941 | 65 | −2,463 |
| 20-day high, stop ATR×2, target 3R, hold 20d, above 50-day avg | 82 | −2,162 | 64 | −3,593 |
| 20-day high, stop 5%, target 3R, hold 20d, above 50-day avg | 85 | −2,396 | 61 | −1,904 |

**0 of 72** variations made money on the train period.

How to read it: a delivery round trip costs about **₹120** at this size (0.1% STT on each side dominates). The best rule lost about ₹5 per trade on train and ₹39 on test, so **before costs it earned roughly ₹80–115 per trade**: a small real tendency for breakouts to continue, not big enough to pay for delivery costs. Trade counts are low (60–100 per period), so this is weak evidence either way.

## Data notes

- Groww returns daily candles with an empty open for roughly the most recent year, and about one 5-minute bar per day without an open. The tools estimate such an open from the previous close, kept inside the bar's high–low range, and report how many were filled. About one empty 5-minute bar per day (no prices) is skipped.
- The daily series includes the Diwali Muhurat session (Sunday 8 Nov 2026).
- Exchange holidays aren't modelled; Groww simply returns no candles for them.

## What it means

- Simple, widely known intraday rules on the most liquid NSE large-caps don't beat costs. A small retail account pays a large share of each trade in fixed and proportional charges.
- The only hint of an edge was in slower, multi-day breakouts, and it was smaller than delivery costs.
- We tried 140 variations in total. Every extra idea tested raises the chance that a "winner" is luck, so a future rule should show a clearly positive result on the unseen period, over many trades, and then hold up in weeks of paper trading before anyone trusts it.

## Reproduce it

```
python3 gtrade.py fetch --days 365
python3 gtrade.py fetch --interval 1440 --days 1100
python3 gtrade.py sweep --source csv --shorts
python3 gtrade.py swing --source csv
```

Numbers will drift as new sessions are added and if Groww's pricing changes. Check `config.json` charges against [groww.in/pricing/stocks](https://groww.in/pricing/stocks) first.
