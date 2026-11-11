# Groww Sweep

Trying 50 variations and keeping the best one almost always finds something that looks profitable by luck. The sweep guards against that by splitting the history by date: it **chooses on the train period** (earlier ~60%) and **reports the test period** (later ~40%), which played no part in the choice.

`gtrade.py` is in the repository root, three folders above this file.

```
python3 <repo>/gtrade.py sweep --source csv                                  # whole watchlist, default grid
python3 <repo>/gtrade.py sweep --setups orb --targets 1.5R,2R,3R --ranges 15,30 --source csv
python3 <repo>/gtrade.py sweep SBIN ICICIBANK --stops pct:0.5,pct:1 --json --write
python3 <repo>/gtrade.py sweep --source csv --walk-forward                # + rolling re-choice
```

**Luck check** (always printed): with N variations, the best one lands about sqrt(2 ln N) standard errors above zero by luck alone (about 2.9 for 68). The pick's train result is shown in the same units (`t_stat`: average trade / its standard error). Below the bar, its train result is what luck produces.

**Walk-forward** (`--walk-forward`, windows `--wf-train 120 --wf-test 40` sessions): choose the best variation on each window, trade it on the next, roll forward, and add up only the unseen results. This tests the search process itself, which is what someone following it would have earned.

Defaults: all four setups (`orb`, `pdh_breakout`, `orb_fade`, `vwap_reclaim`); every stop that suits each setup (`orb`: or_mid, or_low, pct:0.5, pct:1, atr:1.5; `pdh_breakout`: level, pct:...; `orb_fade` and `vwap_reclaim`: setup, pct:...); targets `1R,1.5R,2R,3R`; `--ranges 15,30` tries opening-range lengths for orb and orb_fade; `--shorts` adds short trades; train 60%; a variation needs at least `--min-trades 10` train trades to be ranked. Uses the same fill model, slippage and charges as `groww-check-idea`.

Data: more history makes the verdict stronger. `fetch --days 365` asks Groww for a year in 30-day windows and keeps whatever exists (it reports how far back it got). `--source csv` reuses the cache. For multi-day trades use the swing test (`reference/swing.md`) instead.

## Output

How many variations were tested and how many made money on train; the top 5 by train net with their test results beside them; and a verdict:

- best variation lost on train -> no edge found
- won on train, lost on test -> most likely luck
- won on train, too few test trades -> need more data
- won on both -> worth paper trading, still not proof

## How to report

- Say how many variations were tried and quote the luck check. The more tried, the more suspicious a good train result is.
- If walk-forward was run, its out-of-sample total is the headline number.
- Judge by the **test** column, not train. Never recommend a rule on its train result alone.
- Small samples (under ~30 test trades) are weak evidence; suggest fetching more history.
- A rule that survives goes to `groww-paper` for 2-3 weeks before anything else. Don't suggest live trading.
