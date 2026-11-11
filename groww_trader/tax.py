"""Capital gains tax on delivery (CNC) trades in listed Indian shares.

A simplified model of the rules for STT-paid listed equity (individuals):
  * held 12 months or less: short-term (STCG, section 111A), default 20%
  * held more than 12 months: long-term (LTCG, section 112A), default 12.5%
    on gains above Rs 1.25 lakh per financial year (April-March)
  * a 4% health and education cess on the tax
  * short-term losses can be set off against short- or long-term gains,
    long-term losses only against long-term gains; unused losses carry
    forward (up to 8 years)
Rates as of FY 2026-27 (unchanged by Budget 2026); override in config "tax".

Not modelled: surcharge on high incomes, the slab-rate rebate interplay,
grandfathering of pre-2018 holdings, and intraday (MIS) trading, which is
speculative business income taxed at the person's slab rate. This is an
estimate for comparing strategies, not tax advice.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Tuple

TAX_DEFAULTS = {
    "stcg_pct": 20.0,
    "ltcg_pct": 12.5,
    "ltcg_exempt_per_year": 125000.0,
    "cess_pct": 4.0,
    "long_term_after_days": 365,
}


def params(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {**TAX_DEFAULTS, **(cfg.get("tax") or {})}


def fy(d: date) -> int:
    """Financial year label: April 2026 - March 2027 is 2026."""
    return d.year if d.month >= 4 else d.year - 1


def capital_gains_tax(realised: Iterable[Tuple[date, float, int]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """`realised`: (sell date, gain after charges, days held) per closed lot.
    Returns the tax per financial year and in total."""
    t = params(cfg)
    years: Dict[int, Dict[str, float]] = {}
    for d, gain, held in realised:
        y = years.setdefault(fy(d), {"st": 0.0, "lt": 0.0})
        y["lt" if held > t["long_term_after_days"] else "st"] += gain
    out_years: List[Dict[str, Any]] = []
    carry_st = carry_lt = 0.0  # losses carried forward (positive numbers)
    total = 0.0
    for y in sorted(years):
        st, lt = years[y]["st"], years[y]["lt"]
        # brought-forward losses: short-term against either, long-term against long-term only
        lt_use = min(carry_lt, max(lt, 0.0))
        lt -= lt_use
        carry_lt -= lt_use
        st_use = min(carry_st, max(st, 0.0))
        st -= st_use
        carry_st -= st_use
        st_use2 = min(carry_st, max(lt, 0.0))
        lt -= st_use2
        carry_st -= st_use2
        # this year's set-off
        if st < 0 and lt > 0:
            k = min(-st, lt)
            st += k
            lt -= k
        if st < 0:
            carry_st += -st
            st = 0.0
        if lt < 0:
            carry_lt += -lt
            lt = 0.0
        taxable_lt = max(0.0, lt - t["ltcg_exempt_per_year"])
        tax = (st * t["stcg_pct"] + taxable_lt * t["ltcg_pct"]) / 100 * (1 + t["cess_pct"] / 100)
        total += tax
        out_years.append({"fy": f"{y}-{str(y + 1)[2:]}", "short_term_gain": round(years[y]["st"], 2),
                          "long_term_gain": round(years[y]["lt"], 2), "tax": round(tax, 2)})
    return {"total_tax": round(total, 2), "by_year": out_years,
            "losses_carried_forward": round(carry_st + carry_lt, 2),
            "rates": {k: t[k] for k in ("stcg_pct", "ltcg_pct", "ltcg_exempt_per_year", "cess_pct")}}
