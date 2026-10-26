"""Volume-Weighted Average Rate (VWAR) over a campaign's contributions.

VWAR = SUM(amount * bid) / SUM(amount). The campaign keeps the running numerator
(weighted_yield_sum) and denominator (current_raised), so this is O(1).
"""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def compute_vwar(weighted_yield_sum: Decimal, current_raised: Decimal) -> Decimal | None:
    """Return the rate to 2 decimal places (half-up), or None if nothing is raised yet."""
    if current_raised <= 0:
        return None
    return (weighted_yield_sum / current_raised).quantize(CENT, rounding=ROUND_HALF_UP)
