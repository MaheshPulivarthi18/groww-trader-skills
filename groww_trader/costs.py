"""Indian equity trading charges for one round trip (buy + sell).

Rates come from config["charges"] and are percentages of turnover. The
defaults are typical NSE equity rates, not a quote: verify against your
broker's pricing page. Delivery sells include a DP charge (charges.delivery
.dp_per_sell, Groww: Rs 3.5 depository + Rs 16.5 Groww, plus GST). Platform or
API subscription fees are not included.
"""

from __future__ import annotations

from typing import Any, Dict


def _brokerage(value: float, ch: Dict[str, Any]) -> float:
    if value <= 0:
        return 0.0
    b = value * ch["brokerage_pct"] / 100
    b = max(b, ch.get("brokerage_min", 0))
    if ch.get("brokerage_max"):
        b = min(b, ch["brokerage_max"])
    return b


def round_trip(buy_price: float, sell_price: float, qty: int,
               charges: Dict[str, Any], product: str = "MIS") -> Dict[str, float]:
    """Charges for buying and selling `qty` shares. Works for longs and shorts
    (for a short, the sell happens first; the charges are the same)."""
    buy_v = buy_price * qty
    sell_v = sell_price * qty
    turnover = buy_v + sell_v
    leg = charges["intraday" if product.upper() == "MIS" else "delivery"]

    brokerage = _brokerage(buy_v, charges) + _brokerage(sell_v, charges)
    stt = sell_v * leg["stt_sell_pct"] / 100 + buy_v * leg.get("stt_buy_pct", 0) / 100
    exch = turnover * charges["exchange_txn_pct"] / 100
    sebi = turnover * charges["sebi_pct"] / 100
    stamp = buy_v * leg["stamp_buy_pct"] / 100
    # Delivery sells also pay a depository (DP) charge per sell, GST on top.
    dp = float(leg.get("dp_per_sell", 0)) if product.upper() != "MIS" and sell_v > 0 else 0.0
    gst = (brokerage + exch + sebi + dp) * charges["gst_pct"] / 100
    total = brokerage + stt + exch + sebi + stamp + dp + gst
    return {
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange": round(exch, 2),
        "sebi": round(sebi, 2),
        "stamp": round(stamp, 2),
        "dp": round(dp, 2),
        "gst": round(gst, 2),
        "total": round(total, 2),
    }


def net_pnl(side: str, entry: float, exit_: float, qty: int,
            charges: Dict[str, Any], product: str = "MIS") -> Dict[str, float]:
    if side == "BUY":
        gross = (exit_ - entry) * qty
        c = round_trip(entry, exit_, qty, charges, product)
    else:
        gross = (entry - exit_) * qty
        c = round_trip(exit_, entry, qty, charges, product)
    return {"gross": round(gross, 2), "charges": c["total"], "net": round(gross - c["total"], 2)}
