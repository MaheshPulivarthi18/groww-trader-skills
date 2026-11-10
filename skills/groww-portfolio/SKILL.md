---
name: groww-portfolio
description: Test slow, multi-stock portfolio strategies from the research literature (cross-sectional momentum with a market-regime filter, low volatility, dual momentum between index and gold ETFs) on NSE daily data, after delivery charges, against simply holding the Nifty ETF, with an honest train/test split. Use when the user asks about momentum, factor, rotation or long-term systematic strategies, or wants something more mature than intraday rules.
---

# Groww Portfolio

Mature systematic strategies rank many stocks, hold a handful, rebalance slowly (monthly) and are judged against the index. This is the tool for them.

`gtrade.py` is in the repository root, two folders above this SKILL.md.

```
# data: a universe plus the benchmark ETF, daily candles, as far back as Groww gives
python3 <repo>/gtrade.py fetch --universe nifty100 NIFTYBEES GOLDBEES --interval 1440 --days 2500

python3 <repo>/gtrade.py portfolio --universe nifty100 --source csv                       # 12-1 momentum, top 10
python3 <repo>/gtrade.py portfolio --universe nifty100 --regime cash --weight invvol --source csv
python3 <repo>/gtrade.py portfolio --universe nifty100 --sweep --source csv               # 24 variations
python3 <repo>/gtrade.py portfolio --strategy lowvol --universe nifty100 --source csv
python3 <repo>/gtrade.py portfolio --strategy dualmom --assets NIFTYBEES,GOLDBEES --source csv
```

`--universe nifty50|nifty100|nifty200|nifty500` downloads NSE's current list once (cached in `trader/`); a CSV with a Symbol column, a text file, or `A,B,C` also work.

## Strategies (published ideas, implemented here)

- **momentum**: hold the `--top` stocks with the best return over `--lookback` days, skipping the last `--skip` (default 252 and 21: "12-1 momentum", Jegadeesh & Titman). Only positive scores qualify. NSE runs an index on this idea (Nifty200 Momentum 30).
- **regime filter** (`--regime cash`): hold cash while the benchmark is below its `--sma`-day average, as in Clenow's *Stocks on the Move* and trend-following practice. Mainly reduces big drawdowns.
- **inverse-volatility weights** (`--weight invvol`): calmer stocks get more money (risk-based sizing, Carver's *Systematic Trading*).
- **lowvol**: hold the least volatile stocks (the low-volatility anomaly; NSE has a Nifty Low Vol 30 index).
- **dualmom**: rotate monthly into whichever of `--assets` has the best 12-month return, or cash if none is positive (Antonacci's *Dual Momentum*).

## Execution model

Decisions use closes up to the decision day; orders fill at the next day's open plus slippage; delivery charges on every buy and sell (STT both sides, stamp duty, DP charge on sells, brokerage, fees, GST); whole shares; resizing skipped for changes under `--band` (20%); final value after selling everything. Idle cash earns nothing unless `--cash-yield 6.5` (a liquid fund). The benchmark is bought once and held with the same costs.

## How to report

- Lead with the comparison to the benchmark over the same dates, in both periods. A strategy that doesn't beat simply holding NIFTYBEES isn't worth running, however good its own number looks.
- Give return, worst drawdown, trades and costs. Sharpe uses `--rf` (6.5%).
- Always mention, when an index universe is used: **survivorship bias** (today's members tested on the past flatters results), the short test period, and that Groww leaves daily opens empty for about the last year (estimated from the previous close).
- Taxes aren't modelled. Monthly rotation creates short-term capital gains, taxed more heavily than long-term ones; say so when comparing with buy-and-hold.
- For `--sweep`, judge by the test columns and say how many variations were tried. If the pick beats the index on both periods, the next step is tracking it on paper for months, never going live on a backtest. If similar funds or ETFs exist (momentum, low-vol), the user can compare with those too; that's a fact to weigh, not a recommendation.
