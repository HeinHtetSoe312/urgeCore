from decimal import Decimal

import pytest

from app.services.vwar_service import compute_vwar


@pytest.mark.parametrize(
    ("weighted", "raised", "expected"),
    [
        ("900.0000", "150.00", "6.00"),  # 100 @ 5% and 50 @ 8%
        ("170.0000", "30.00", "5.67"),  # 10 @ 4%, 10 @ 5%, 10 @ 8%: 5.6667 rounds up
        ("1.0000", "8.00", "0.13"),  # exactly 0.125: ROUND_HALF_UP, not banker's rounding
        ("500.0000", "100.00", "5.00"),
    ],
)
def test_vwar_is_volume_weighted_and_rounds_half_up(weighted, raised, expected):
    assert compute_vwar(Decimal(weighted), Decimal(raised)) == Decimal(expected)


def test_vwar_is_none_when_nothing_is_raised():
    assert compute_vwar(Decimal("0"), Decimal("0.00")) is None
