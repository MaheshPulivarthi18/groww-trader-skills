---
name: groww-budget
description: Size each planned trade so the loss at the stop, including Indian charges (brokerage, STT, exchange, SEBI, stamp duty, GST), stays inside the user's per-trade limit and capital cap. Reads trader/plan.json, writes trader/orders.json. Use when the user asks how many shares to buy or how much to risk.
---

# Groww Budget

Turns plans into order tickets with a quantity. Reads `trader/plan.json`, writes `trader/orders.json`.

`gtrade.py` is in the repository root, two folders above this SKILL.md.

```
python3 <repo>/gtrade.py size --write
```

## The math

1. `by_risk = floor(max_loss_per_trade / |entry - stop|)`
2. `by_capital = floor(capital x max_position_pct% / entry)` (no leverage assumed)
3. `qty = min(by_risk, by_capital)`, then reduced one share at a time until the loss at the stop **after charges** fits the limit.

Each ticket shows `qty`, `value`, `loss_at_stop`, `profit_at_target`, `charges_est`, and `limited_by` (risk or capital). `paper` comes from config and defaults to true.

## How to report

Show each ticket in rupees, e.g. "Buy 246 at about ₹101.60: lose ~₹309 if stopped, make ~₹367 at target (charges ~₹39 either way)." If `qty` is 0, say why (the stop is too far for the per-trade limit) rather than suggesting a bigger limit. Next step: `groww-risk`.

Charges use the rates in config `charges`. They are defaults, not a quote; the user should match them to Groww's pricing page.
