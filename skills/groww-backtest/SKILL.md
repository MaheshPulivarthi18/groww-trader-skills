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

## Fill model (conservative on purpose)

- Entry at the **open of the bar after** the trigger bar, plus slippage.
- If one bar touches both stop and target, the **stop** counts first.
- A gap through the stop fills at the bar's open, not the stop.
- Still open at `flat_by`: exit at that bar's open.
- Slippage (`slippage_pct`, per side) and full charges on every trade.

## Output

`stats`: trades, wins, losses, win rate, exits by reason, gross, charges, net, average net, average R, profit factor, max drawdown, best/worst. `not_triggered`: why other sessions had no trade. `outlook`: 10,000 resamples of past trades for the next N (default 20): 5th percentile, median, 95th percentile, chance of a loss. Seeded, so it repeats exactly.

## How to report

- Lead with **net after charges** and how much the charges took. For intraday, charges often turn a break-even rule into a loser; say so plainly when it happens.
- Give the sample size. Under ~30 trades, call the result weak evidence.
- The outlook is resampled history, not a forecast; markets change.
- Never present a good backtest as a reason to trade live. Suggest paper trading it next, and testing the same rule on other stocks and other months to see if it holds.
