# Groww Swing

Intraday rules fight about 0.2% of costs on every trade. Swing trades aim for bigger moves over days, so costs are a smaller share, but delivery has its own: STT 0.1% on both buy and sell, stamp duty 0.015%, brokerage, exchange/SEBI fees, GST and a DP charge (Groww: Rs 20 + GST) on each sell.

`gtrade.py` is in the repository root, three folders above this file.

```
python3 <repo>/gtrade.py fetch --interval 1440 --days 1100      # daily candles, ~3 years
python3 <repo>/gtrade.py swing --source csv                     # default grid: 72 variations
python3 <repo>/gtrade.py swing SBIN LT --lookbacks 55 --stops atr:2 --targets 3R,none --holds 20 --trends 50 --source csv
```

## The rule

Signal when the day's close is above the highest high of the previous `lookback` days (and above its `trend`-day average when `trend` > 0). Buy at the next day's open plus slippage. Then each day: stop first (a gap below fills at the open, with extra slippage), then target (needs a trade a tick beyond it; `none` = no target), else sell at the close after `hold` days. Longs only, one position per stock, sized by the user's `max_loss_per_trade` and `max_position_pct` after delivery charges.

Defaults: lookbacks `20,55`; stops `pct:3,pct:5,atr:2` (daily ATR14); targets `2R,3R,none`; holds `10,20` days; trends `0,50`; train 60% of days; at least 8 train trades to rank.

## How to report

Same as the sweep (`reference/sweep.md`): say how many variations were tried, judge by the **test** column, give trade counts (swing produces few trades, so evidence is thin: call anything under ~30 test trades weak), and quote the verdict. Overlapping rules (e.g. with and without the trend filter) often give identical rows; that isn't extra evidence.

There is no swing paper-trading mode yet. If a rule survives, suggest the user tracks its signals by hand (or in a sheet) for a few months before trusting it. Never suggest live trading on a backtest.
