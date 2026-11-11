"""One scorecard for every test: plain pass/fail lines and a verdict.

Checks, in the order a sceptic would ask them:
  1. enough trades to judge at all
  2. entries beat random timing (the random-entry baseline)
  3. profitable after charges
  4. profitable in both the earlier and the later part of the period
  5. worst drawdown tolerable for the account
plus a cost line: how much of the average trade the charges take.

The verdict is chosen from the combination, worst news first. It describes
the past only; even a full pass is a reason to paper-track, never to trade.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

PASS, FAIL, WEAK, SKIP = "PASS", "FAIL", "WEAK", "n/a"

MIN_TRADES = 30          # below this, nothing can be concluded
GOOD_TRADES = 100        # below this, conclusions are weak
MAX_DD_PCT = 15.0        # worst peak-to-trough as % of capital
EARLY_SHARE = 0.6        # the "earlier" part of the period, by trading days


def _split_net(trades: List[Dict[str, Any]], calendar: List[str]) -> Optional[tuple]:
    if not calendar:
        return None
    cut = calendar[min(len(calendar) - 1, int(len(calendar) * EARLY_SHARE))]
    early = [t for t in trades if t["day"] < cut]
    late = [t for t in trades if t["day"] >= cut]
    return cut, early, late


def build(res: Dict[str, Any], trades: List[Dict[str, Any]], calendar: List[str]) -> Dict[str, Any]:
    st = res.get("stats") or {}
    n = st.get("trades", 0)
    cap = res.get("capital") or 0
    checks = []

    def add(status, name, detail):
        checks.append({"status": status, "check": name, "detail": detail})

    # 1. sample size
    if n < MIN_TRADES:
        add(FAIL, "Enough trades to judge", f"{n} trades; at least {MIN_TRADES} are needed to say anything")
    elif n < GOOD_TRADES:
        add(WEAK, "Enough trades to judge", f"{n} trades; under {GOOD_TRADES}, treat every result as rough")
    else:
        add(PASS, "Enough trades to judge", f"{n} trades over {res.get('sessions', '?')} sessions")

    # 2. random baseline
    vr = res.get("vs_random_entries") or {}
    beats = vr.get("beats_random")
    if "share_of_random_runs_as_good_pct" not in vr:
        add(SKIP, "Entries beat random timing", vr.get("note", "not run (use --baseline)"))
    else:
        share = vr["share_of_random_runs_as_good_pct"]
        add(PASS if beats else FAIL, "Entries beat random timing",
            f"{share}% of {vr['runs']} random-timed versions did as well or better "
            f"(real Rs {vr['real']['net']:,.0f} vs random median Rs {vr['random_net']['median']:,.0f})")

    # 3. profit after charges
    net = st.get("net_total", 0.0)
    if n:
        add(PASS if net > 0 else FAIL, "Profitable after charges",
            f"net Rs {net:,.0f} ({res.get('return_on_capital_pct', 0)}% of capital); "
            f"before charges Rs {st.get('gross_total', 0):,.0f}, charges Rs {st.get('charges_total', 0):,.0f}")
    else:
        add(FAIL, "Profitable after charges", "no trades")

    # 4. consistency over time
    sp = _split_net(trades, calendar) if n else None
    if sp and n >= MIN_TRADES:
        cut, early, late = sp
        en, ln = sum(t["net"] for t in early), sum(t["net"] for t in late)
        ok = en > 0 and ln > 0
        add(PASS if ok else FAIL, "Holds up in both halves of the period",
            f"before {cut}: Rs {en:,.0f} on {len(early)} trades; from {cut}: Rs {ln:,.0f} on {len(late)} trades")
    else:
        add(SKIP, "Holds up in both halves of the period", "too few trades to split")

    # 5. drawdown
    dd = st.get("max_drawdown", 0.0)
    if n and cap:
        dd_pct = round(100 * -dd / cap, 1)
        add(PASS if dd_pct <= MAX_DD_PCT else FAIL, "Worst drawdown tolerable",
            f"worst fall from a peak Rs {-dd:,.0f} = {dd_pct}% of capital (limit {MAX_DD_PCT}%)")

    # cost line (information, not pass/fail)
    cost_line = None
    if n:
        per_trade_charges = st.get("charges_total", 0) / n
        per_trade_gross = st.get("gross_total", 0) / n
        cost_line = (f"Average trade made Rs {per_trade_gross:,.2f} before charges and paid "
                     f"Rs {per_trade_charges:,.2f} in charges.")

    verdict, next_step = _verdict(n, beats, net, checks)
    return {"checks": checks, "costs": cost_line, "verdict": verdict, "next_step": next_step,
            "note": "Describes the past only, with simulated fills. Not investment advice; no orders are placed."}


def _verdict(n, beats, net, checks):
    status = {c["check"]: c["status"] for c in checks}
    if n < MIN_TRADES:
        return ("NOT ENOUGH DATA: too few trades to tell anything.",
                "Test more days or more stocks before drawing any conclusion.")
    if beats is False and net <= 0:
        return ("NO EDGE: entries are no better than random, and it loses after charges.",
                "Don't trade it. Tuning stops and targets won't create an edge; try a different idea.")
    if beats and net <= 0:
        return ("REAL SIGNAL, TOO SMALL FOR THE COSTS: entries beat random, but charges eat the edge.",
                "Look for bigger moves per trade (fewer trades, longer holding) rather than tuning.")
    if net > 0 and beats is False:
        return ("PROFIT LOOKS LIKE LUCK: it made money, but random entries did about as well.",
                "Likely market drift or chance. Don't trust it without a signal that beats random.")
    if net > 0 and beats is None:
        return ("UNCHECKED PROFIT: made money, but it wasn't compared with random entries.",
                "Run it again with the random-entry check before believing it.")
    if all(status.get(k) in (PASS, WEAK) for k in status):
        return ("PASSES EVERY CHECK on past data.",
                "Paper-track it for 1-3 months and compare with this result. A backtest is not proof.")
    failed = [k for k, v in status.items() if v == FAIL]
    return ("PROMISING BUT FRAGILE: profitable and beats random, but fails: " + ", ".join(failed) + ".",
            "Paper-track only, and find out why it fails those checks first.")


def render(card: Dict[str, Any], header: str = "") -> str:
    icon = {PASS: "PASS", FAIL: "FAIL", WEAK: "WEAK", SKIP: " -- "}
    lines = [header] if header else []
    for c in card["checks"]:
        lines.append(f"  [{icon[c['status']]}] {c['check']}: {c['detail']}")
    if card.get("costs"):
        lines.append(f"  [cost] {card['costs']}")
    lines += ["", f"VERDICT: {card['verdict']}", f"Next: {card['next_step']}", "", card["note"]]
    return "\n".join(lines)
