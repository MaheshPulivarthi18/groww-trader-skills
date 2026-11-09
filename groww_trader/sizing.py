"""Position sizing: how many shares so that the loss at the stop, INCLUDING
charges, stays inside the per-trade limit. No leverage is assumed."""

from __future__ import annotations

import math
from typing import Any, Dict

from .costs import net_pnl


def size(plan: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    risk = cfg["risk"]
    entry, stop, target, side = plan["entry"], plan["stop"], plan["target"], plan["side"]
    product = cfg.get("product", "MIS")
    max_loss = float(risk["max_loss_per_trade"])
    per_share = abs(entry - stop)

    by_risk = math.floor(max_loss / per_share) if per_share > 0 else 0
    by_cap = math.floor(cfg["capital"] * risk["max_position_pct"] / 100 / entry)
    qty = max(0, min(by_risk, by_cap))
    # Charges eat into the budget: step down until loss-at-stop fits.
    while qty > 0 and -net_pnl(side, entry, stop, qty, cfg["charges"], product)["net"] > max_loss:
        qty -= 1

    order = {
        **plan,
        "qty": qty,
        "product": product,
        "exchange": cfg.get("exchange", "NSE"),
        "order_type": "LIMIT",
        "limit_price": entry,
        "value": round(qty * entry, 2),
        "limited_by": "capital" if by_cap < by_risk else "risk",
        "paper": bool(cfg.get("paper", True)),
    }
    if qty:
        at_stop = net_pnl(side, entry, stop, qty, cfg["charges"], product)
        at_target = net_pnl(side, entry, target, qty, cfg["charges"], product)
        order.update({"loss_at_stop": at_stop["net"], "profit_at_target": at_target["net"],
                      "charges_est": at_target["charges"]})
    else:
        order["reason"] = "position too small: per-share risk exceeds the per-trade loss limit"
    return order
