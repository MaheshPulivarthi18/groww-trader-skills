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



def break_even(value: float, charges: Dict[str, Any], product: str = "MIS",
               stop_pct: float = 0.0, slippage_pct: float = 0.0) -> Dict[str, Any]:
    """What one round trip of `value` rupees costs (bought and sold at the
    same price), and how far the price must move before the trade makes a
    rupee. With stop_pct, also how the costs compare with the money at risk.
    Charges are linear in value except brokerage's Rs 5 floor and Rs 20 cap,
    so computing them on value directly (price 1, qty = value) is exact."""
    c = _round_trip_value(value, charges, product)
    slip = round(value * 2 * slippage_pct / 100, 2)
    out: Dict[str, Any] = {
        "trade_value": round(value, 2),
        "product": "intraday (MIS)" if product.upper() == "MIS" else "delivery (CNC)",
        "charges": c,
        "break_even_move_pct": round(100 * c["total"] / value, 3) if value else None,
    }
    if slippage_pct:
        out["slippage_estimate"] = slip
        out["break_even_with_slippage_pct"] = round(100 * (c["total"] + slip) / value, 3) if value else None
    if stop_pct and value:
        risk = value * stop_pct / 100
        out["risk_at_stop"] = round(risk, 2)
        out["costs_as_pct_of_risk"] = round(100 * (c["total"] + slip) / risk, 1)
    return out


def _round_trip_value(value: float, charges: Dict[str, Any], product: str) -> Dict[str, float]:
    # one "share" priced at the whole value: per-order brokerage floor/cap apply correctly
    return round_trip(value, value, 1, charges, product)
