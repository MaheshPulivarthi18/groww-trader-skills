from groww_trader import scorecard, costs
from groww_trader.config import DEFAULTS


def _res(n, net, gross, beats, share=50.0, dd=-500, cap=20000):
    st = {"trades": n, "net_total": net, "gross_total": gross, "charges_total": gross - net,
          "max_drawdown": dd} if n else {"trades": 0}
    r = {"stats": st, "capital": cap, "sessions": 250, "return_on_capital_pct": round(100 * net / cap, 2)}
    if beats is not None:
        r["vs_random_entries"] = {"beats_random": beats, "share_of_random_runs_as_good_pct": share,
                                  "runs": 300, "real": {"net": net}, "random_net": {"median": 0}}
    return r


def _trades(n, each):
    days = [f"2026-{1 + i * 10 // n:02d}-{1 + i % 27:02d}" for i in range(n)]
    return [{"day": d, "net": each} for d in sorted(days)], sorted(set(days))


def test_no_edge_verdict():
    tr, cal = _trades(150, -20)
    card = scorecard.build(_res(150, -3000, 500, False, share=70), tr, cal)
    assert card["verdict"].startswith("NO EDGE")
    assert {c["check"]: c["status"] for c in card["checks"]}["Entries beat random timing"] == "FAIL"


def test_signal_too_small_and_luck_and_unchecked():
    tr, cal = _trades(150, -5)
    assert scorecard.build(_res(150, -750, 2000, True, share=2), tr, cal)["verdict"].startswith("REAL SIGNAL")
    tr, cal = _trades(150, 5)
    assert scorecard.build(_res(150, 750, 4000, False, share=40), tr, cal)["verdict"].startswith("PROFIT LOOKS LIKE LUCK")
    assert scorecard.build(_res(150, 750, 4000, None), tr, cal)["verdict"].startswith("UNCHECKED")


def test_full_pass_and_fragile():
    tr, cal = _trades(150, 10)
    card = scorecard.build(_res(150, 1500, 5000, True, share=1), tr, cal)
    assert card["verdict"].startswith("PASSES"), card
    card = scorecard.build(_res(150, 1500, 5000, True, share=1, dd=-6000), tr, cal)
    assert card["verdict"].startswith("PROMISING BUT FRAGILE") and "drawdown" in card["verdict"]


def test_too_few_trades():
    tr, cal = _trades(12, 10)
    assert scorecard.build(_res(12, 120, 400, True, share=1), tr, cal)["verdict"].startswith("NOT ENOUGH")


def test_render_has_every_check():
    tr, cal = _trades(150, -20)
    text = scorecard.render(scorecard.build(_res(150, -3000, 500, False), tr, cal), "hdr")
    assert "VERDICT:" in text and "no orders are placed" in text and text.count("[") >= 5


def test_break_even_matches_groww_example():
    ch = DEFAULTS["charges"]
    r = costs.break_even(10000, ch, "MIS")
    assert abs(r["charges"]["total"] - 27.15) < 0.05 and abs(r["break_even_move_pct"] - 0.272) < 0.002
    small = costs.break_even(2000, ch, "MIS")  # Rs 5 minimum brokerage bites on small orders
    assert small["charges"]["brokerage"] == 10 and small["break_even_move_pct"] > 0.6
    d = costs.break_even(10000, ch, "CNC", stop_pct=1.0)
    assert d["charges"]["dp"] == 20 and d["costs_as_pct_of_risk"] > 60
