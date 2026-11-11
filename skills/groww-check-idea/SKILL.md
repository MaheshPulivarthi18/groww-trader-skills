---
name: groww-check-idea
description: Check whether a trading idea for Indian stocks actually works before risking money - turn the user's plain-words rule into a test on NSE data, run it after real Groww charges against random entry timing, and give a pass/fail scorecard and verdict. Use when the user describes a strategy, asks "does this work", "should I trade this", wants a backtest, an optimisation, swing or long-term (momentum, rotation) testing. Never places orders.
---

# Check my trading idea

The front door of this toolkit. A user says something like "buy when a stock breaks its first 15-minute high, stop halfway, target 2x", and gets an honest answer: does it beat chance, does it survive charges, and does it hold up over time.

`gtrade.py` is in the repository root, two folders above this SKILL.md. Run it as `python3 <repo>/gtrade.py ...` (`gt` if the user has the alias). It needs cached data in `trader/data/` (`--source csv`) or Groww credentials (`groww-setup`).

## 1. Translate the idea

Map what the user said onto the building blocks below. Say back, in one or two lines, how you translated it, and **name every part that can't be tested** (e.g. news, options, indicators not listed) rather than quietly dropping it.

| User says | Test with |
|---|---|
| breaks the first 15/30-min high (opening range breakout) | `--setup orb`; range length `setups.orb.range_min` |
| breaks yesterday's high | `--setup pdh_breakout` |
| fade / fails a breakout and reverses | `--setup orb_fade` |
| back above VWAP after being below | `--setup vwap_reclaim` |
| also shorting | `--shorts` |
| stop: middle / bottom of the range, the broken level, x%, x ATR | `--stop or_mid` / `or_low` / `level` / `pct:1` / `atr:1.5` |
| target 1.5x / 2x the risk | `--target 1.5R` / `2R` |
| holds for days or weeks, breakouts on daily charts | swing test: read `reference/swing.md` |
| monthly rotation, momentum, low volatility, index vs gold | portfolio test: read `reference/portfolio.md` |
| capital, risk per trade, daily loss, positions, entry times | `trader/config.json` (`capital`, `risk.*`); ask before changing it |

If the idea doesn't fit at all, say so plainly and suggest the nearest testable version; don't pretend.

## 2. Run the scorecard (intraday ideas)

```
python3 <repo>/gtrade.py evaluate --setup orb --stop or_mid --target 1.5R --source csv
python3 <repo>/gtrade.py evaluate RELIANCE SBIN --setup pdh_breakout --stop level --target 2R --source csv
python3 <repo>/gtrade.py evaluate --setup orb --days 365 --baseline 500 --json      # full detail
```

It tests the whole watchlist (or the symbols given) as **one account** with the user's limits, over `--days` (default 365), and checks:

1. **Enough trades** (30 minimum, 100 for confidence)
2. **Entries beat random timing**: each real trade is replayed at random entry times on the same stock and day, same stop %, target and charges, `--baseline` times (default 300). If 5% or fewer random runs did as well, the entry signal is real.
3. **Profitable after charges**
4. **Holds up in both halves** of the period (earlier 60% and later 40% of days)
5. **Worst drawdown** within 15% of capital

plus a cost line (average trade before charges vs charges paid) and a verdict: `NO EDGE`, `REAL SIGNAL, TOO SMALL FOR THE COSTS`, `PROFIT LOOKS LIKE LUCK`, `PROMISING BUT FRAGILE`, `PASSES EVERY CHECK` or `NOT ENOUGH DATA`.

If data is missing: `gtrade.py fetch --interval 5 --days 365` (Groww gives roughly the last year of 5-minute candles).

## 3. Report

- **Lead with the verdict line**, then the checks that failed, then the cost line. Use rupees.
- Explain "beats random" simply: "buying at random times on the same days did as well in X% of 500 tries".
- If the entries don't beat random, say plainly that changing stops and targets won't create an edge. Don't offer to tune it.
- Never call a passing scorecard a reason to trade real money. The next step for a pass is paper tracking (`groww-paper`) for 1-3 months.
- Past data, simulated fills. Not investment advice.

## Going further (read the reference file first)

- `reference/intraday-backtest.md`: one stock in detail, every trade (`backtest SYMBOL --trades`), fill model.
- `reference/sweep.md`: trying many variations. Only after a rule beats random; warn that the best of many versions always looks better than it is.
- `reference/swing.md`: multi-day breakout rules on daily candles, delivery charges.
- `reference/portfolio.md`: momentum, low-volatility and dual-momentum portfolios against the Nifty ETF.

To see what any trade size costs, use `groww-costs`.
