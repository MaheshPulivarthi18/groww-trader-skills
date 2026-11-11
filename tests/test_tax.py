from datetime import date

from groww_trader.tax import capital_gains_tax, fy

CFG = {}


def test_financial_year():
    assert fy(date(2026, 4, 1)) == 2026 and fy(date(2027, 3, 31)) == 2026 and fy(date(2026, 3, 31)) == 2025


def test_short_term_and_cess():
    r = capital_gains_tax([(date(2026, 6, 1), 10000, 30)], CFG)
    assert r["total_tax"] == round(10000 * 0.20 * 1.04, 2)


def test_long_term_exemption():
    r = capital_gains_tax([(date(2026, 6, 1), 200000, 400)], CFG)
    assert r["total_tax"] == round(75000 * 0.125 * 1.04, 2)
    assert capital_gains_tax([(date(2026, 6, 1), 100000, 400)], CFG)["total_tax"] == 0


def test_set_off_and_carry_forward():
    # short-term loss offsets long-term gain in the same year
    r = capital_gains_tax([(date(2026, 6, 1), -50000, 10), (date(2026, 7, 1), 200000, 400)], CFG)
    assert r["total_tax"] == round(25000 * 0.125 * 1.04, 2)
    # long-term loss can't offset short-term gain; it carries forward
    r = capital_gains_tax([(date(2026, 6, 1), -30000, 400), (date(2026, 7, 1), 10000, 10)], CFG)
    assert r["total_tax"] == round(10000 * 0.2 * 1.04, 2) and r["losses_carried_forward"] == 30000
    # a short-term loss carried into next year reduces next year's gain
    r = capital_gains_tax([(date(2026, 6, 1), -10000, 10), (date(2027, 6, 1), 30000, 10)], CFG)
    assert r["by_year"][1]["tax"] == round(20000 * 0.2 * 1.04, 2)
