# Groww Budget

Turns plans into trade tickets with a quantity (paper tickets: nothing is sent to Groww). Reads `trader/plan.json`, writes `trader/orders.json`.

`gtrade.py` is in the repository root, three folders above this file.

```
python3 <repo>/gtrade.py size --write
```

## The math

1. `by_risk = floor(max_loss_per_trade / |entry - stop|)`
2. `by_capital = floor(capital x max_position_pct% / entry)` (no leverage assumed)
3. `qty = min(by_risk, by_capital)`, then reduced one share at a time until the loss at the stop **after charges** fits the limit.

Each ticket shows `qty`, `value`, `loss_at_stop`, `profit_at_target`, `charges_est`, and `limited_by` (risk or capital). `paper` comes from config and defaults to true.

## How to report

Show each ticket in rupees, e.g. "Buy 246 at about ₹101.60: lose ~₹309 if stopped, make ~₹367 at target (charges ~₹39 either way)." If `qty` is 0, say why (the stop is too far for the per-trade limit) rather than suggesting a bigger limit. Next step: the risk gate (`reference/risk-gate.md`).

Charges use the rates in config `charges`. They are defaults, not a quote; the user should match them to Groww's pricing page.
