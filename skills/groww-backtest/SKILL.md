---
name: groww-backtest
description: Replay a setup and its exit rules over past NSE sessions with Groww historical candles, after slippage and Indian charges, and show win rate, net P&L, drawdown and a resampled range of outcomes for the next trades. Use when the user asks whether a setup works, wants to test a strategy, or before risking real money on one.
---

# Groww Backtest

Answers "how did this exact rule do on this stock, after costs?" Writes `trader/backtest.json`.

`gtrade.py` is in the repository root, two folders above this SKILL.md.

```
python3 <repo>/gtrade.py backtest SBIN --setup orb --days 60 --write
python3 <repo>/gtrade.py backtest SBIN --setup pdh_breakout --stop level --target 2R
python3 <repo>/gtrade.py backtest SBIN --source csv --trades     # offline, list every trade
```

Groww serves 5-minute candles in windows of up to 30 days per request; the tool splits longer ranges and caches them in `trader/data/`.

## Setups

`orb` (opening-range breakout), `pdh_breakout` (previous-day high/low), `orb_fade` (failed opening-range breakout traded in reverse; stop beyond the failed move), `vwap_reclaim` (close back above the session VWAP after `min_bars_away` closes below; stop at the low of that stretch). `--shorts` also takes short trades.

## Fill model (conservative on purpose; config `fills`)

- Entry at the **open of the bar after** the trigger bar, plus slippage (`fills.entry: "mid"` is a harsher stress test).
- Targets are limit orders: filled only if price **trades a tick beyond** the target, at the target (no slippage). A touch isn't a fill.
- Stops are market orders: slippage plus `fills.stop_extra_slippage_pct`. A gap through the stop fills at the bar's open.
- If one bar reaches both stop and target, the **stop** counts first.
- Still open at `flat_by`: exit at that bar's open, with slippage.
- Full charges on every trade.

## Output

`stats`: trades, wins, losses, win rate, exits by reason, gross, charges, net, average net, average R, profit factor, max drawdown, best/worst. `not_triggered`: why other sessions had no trade. `outlook`: 10,000 resamples of past trades for the next N (default 20): 5th percentile, median, 95th percentile, chance of a loss. Seeded, so it repeats exactly.

## How to report

- Lead with **net after charges** and how much the charges took. For intraday, charges often turn a break-even rule into a loser; say so plainly when it happens.
- Give the sample size. Under ~30 trades, call the result weak evidence.
- The outlook is resampled history, not a forecast; markets change.
- Never present a good backtest as a reason to trade live. Suggest paper trading it next, and testing the same rule on other stocks and other months to see if it holds.
