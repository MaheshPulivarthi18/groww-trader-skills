"""The toolkit must never place, modify or cancel orders. Two guards:
a static scan of the code, and a read-only wrapper around the SDK client."""
import re
from pathlib import Path

import pytest

from groww_trader.data import ReadOnlyClient

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(
    r"\b(place|modify|cancel|create|exit|square_?off)_\w*order\w*\b|smart_order|\bgtt\b|/orders?/",
    re.IGNORECASE)


def _code_files():
    for p in [ROOT / "gtrade.py", *sorted((ROOT / "groww_trader").glob("*.py"))]:
        yield p


def test_no_order_calls_anywhere_in_code():
    hits = []
    for p in _code_files():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN.search(line):
                hits.append(f"{p.name}:{i}: {line.strip()}")
    assert not hits, "order-related code found:\n" + "\n".join(hits)


class _FakeSDK:
    EXCHANGE_NSE = "NSE"

    def get_ltp(self, *a, **k):
        return {"NSE_SBIN": 800.0}

    def place_order(self, *a, **k):  # what the real SDK has; must never be reachable
        raise AssertionError("order reached the SDK")

    def cancel_order(self, *a, **k):
        raise AssertionError("order reached the SDK")


def test_read_only_client_blocks_order_methods():
    c = ReadOnlyClient(_FakeSDK())
    assert c.get_ltp() == {"NSE_SBIN": 800.0}
    assert c.EXCHANGE_NSE == "NSE"
    for name in ("place_order", "cancel_order", "modify_order", "create_smart_order", "anything_else"):
        with pytest.raises(PermissionError):
            getattr(c, name)
    with pytest.raises(PermissionError):
        c.place_order = lambda: None
