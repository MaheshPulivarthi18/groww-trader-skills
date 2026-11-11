# Groww Portfolio

Mature systematic strategies rank many stocks, hold a handful, rebalance slowly (monthly) and are judged against the index. This is the tool for them.

`gtrade.py` is in the repository root, three folders above this file.

```
# data: a universe plus the benchmark ETF, daily candles, as far back as Groww gives
python3 <repo>/gtrade.py fetch --universe nifty100 NIFTYBEES GOLDBEES --interval 1440 --days 2500

python3 <repo>/gtrade.py portfolio --universe nifty100 --source csv                       # 12-1 momentum, top 10
python3 <repo>/gtrade.py portfolio --universe nifty100 --regime cash --weight invvol --source csv
python3 <repo>/gtrade.py portfolio --universe nifty100 --sweep --source csv               # 24 variations
python3 <repo>/gtrade.py portfolio --strategy lowvol --universe nifty100 --source csv
python3 <repo>/gtrade.py portfolio --strategy dualmom --assets NIFTYBEES,GOLDBEES --source csv
python3 <repo>/gtrade.py portfolio --universe nifty100 --sweep --walk-forward --source csv   # rolling re-choice

# longer, official history with no Groww account: NSE bhavcopies (polite download, cached per day)
python3 <repo>/gtrade.py nse fetch --years 7
python3 <repo>/gtrade.py nse build --universe nifty100          # also builds NIFTYBEES, GOLDBEES
python3 <repo>/gtrade.py portfolio --universe nifty100 --source nse
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

## Data corrections (automatic)

- **Splits, bonuses, demergers:** Groww's daily prices aren't adjusted, so a 1:1 bonus looks like a -50% day. `portfolio` and `swing` adjust them: drops of about 29%+ that match a standard factor (1.5, 2, 3, 5, 10...) are treated as splits/bonuses; unexplained drops of about 37%+ (e.g. demergers) by the observed ratio. `gtrade.py audit --universe nifty100` lists every adjustment. A genuine crash can be mistaken for one (e.g. a -36% day snapping to a 1:2 bonus): cancel it with a line `SYMBOL,YYYY-MM-DD,1` in `trader/corporate_actions.csv`, or force a factor the same way. `--no-adjust` turns it off.
- **Benchmark history:** Groww's NIFTYBEES history starts in January 2025 (NSE bhavcopy data goes back much further). Where the ETF doesn't cover a period, results are judged against the universe's own equal-weight index (built from the data, no costs: a generous yardstick), and the regime filter uses that index too. The output says which benchmark each period used.

## Random stock picks (`--baseline 100`, default)

Beating the index isn't enough: in a rising market, holding any 10 stocks may beat it. Each random run follows the strategy's own schedule: the same rebalance days, the same number of holdings (none when the strategy is in cash), the same number of names swapped each rebalance (so turnover and costs match), the same weighting, charges and slippage, but the stocks are picked at random from those with enough history. If 5% or fewer random runs did as well, the selection rule itself adds something. Reported per period, with a plain verdict.

## Tax (estimated)

Every period also shows the return **after capital gains tax**: realised gains are matched to purchases first-in-first-out; held 12 months or less = short-term (20%), longer = long-term (12.5% above Rs 1.25 lakh per financial year), 4% cess, losses set off and carried forward. The ETF is taxed the same way, so the comparison is fair. Monthly rotation creates mostly short-term gains, so tax hurts it far more than buy-and-hold. Rates as of FY 2026-27 (config `tax` to change). Not tax advice; surcharge isn't modelled.

## Walk-forward (`--sweep --walk-forward`)

Choose the best variation on `--wf-train` days (default 504, ~2 years), hold it for the next `--wf-test` (252, ~1 year), roll forward, and chain the held periods. That is what following the search would have earned. Quote the chained result against the benchmark and how many windows beat it.

## How to report

- Lead with the comparison to the benchmark over the same dates, in both periods. A strategy that doesn't beat simply holding NIFTYBEES isn't worth running, however good its own number looks.
- Give return, worst drawdown, trades and costs. Sharpe uses `--rf` (6.5%).
- Always mention, when an index universe is used: **survivorship bias** (today's members tested on the past flatters results), the short test period, and that Groww leaves daily opens empty for about the last year (estimated from the previous close).
- Quote the after-tax comparison too; monthly rotation's short-term gains are taxed far more heavily than buy-and-hold.
- Lead with whether selection beat random picks. If it didn't, any win over the index came from being invested in these stocks in this period, not from the rule.
- For `--sweep`, judge by the test columns and say how many variations were tried. If the pick beats the index on both periods, the next step is tracking it on paper for months, never going live on a backtest. If similar funds or ETFs exist (momentum, low-vol), the user can compare with those too; that's a fact to weigh, not a recommendation.
