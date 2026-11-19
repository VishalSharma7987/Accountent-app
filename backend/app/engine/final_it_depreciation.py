"""Income-tax block depreciation working with the half-rate rule (Phase 6, package B; rules F-30 .. F-34). Pure Python, Decimal only.

A WORKING only: no voucher, no ledger effect. The rate, the half-rate day limit and the half-rate percentage are inputs (read from the
rule tables by date); this module owns no legal value. Cases the law treats specially (terminal depreciation, additional depreciation,
assets of a business not in use, a block whose disposals exceed it = short-term capital gain) are FLAGGED, never computed (F-33).
"""

from datetime import date
from decimal import Decimal

from app.engine.final_types import ZERO, ItBlockInput, ItBlockResult
from app.engine.money import round_half_up


def _days(start: date, end: date) -> int:
    return (end - start).days + 1


def it_block_depreciation(inp: ItBlockInput, assets_remaining: int | None = None) -> ItBlockResult:
    """F-30..F-33. `assets_remaining`: registered depreciable assets still in the block at the year end (None = no register asset ever
    belonged to the block, so nothing can be said)."""
    additions_full = additions_half = ZERO
    for _asset, cost, put_to_use in inp.additions:
        if _days(put_to_use, inp.fy_end) < inp.half_rate_days:      # F-31: FEWER than the limit -> half rate
            additions_half += cost
        else:
            additions_full += cost
    disposals = sum((amount for _asset, amount in inp.disposals), ZERO)

    # F-32: the disposal is first set against the full-rate base, a deficit against the half-rate additions
    base_full = inp.opening_wdv + additions_full - disposals
    base_half = additions_half
    flags: list[str] = []
    excess = ZERO
    if base_full < 0:
        base_half += base_full
        base_full = ZERO
        if base_half < 0:
            excess = -base_half
            base_half = ZERO
            flags.append("negative_block")

    if "negative_block" in flags:
        depreciation = ZERO
        closing = ZERO
    else:
        half_factor = inp.half_rate_percent / 100
        depreciation = round_half_up(base_full * inp.rate_percent / 100 + base_half * inp.rate_percent / 100 * half_factor, 2)
        closing = round_half_up(inp.opening_wdv + additions_full + additions_half - disposals - depreciation, 2)

    if assets_remaining == 0 and closing > 0:
        flags.append("terminal_depreciation_review")

    details = {
        "base_full": f"{base_full:.2f}", "base_half": f"{base_half:.2f}", "rate_verification": inp.rate_verification,
        "half_rate_days": inp.half_rate_days, "half_rate_percent": f"{inp.half_rate_percent:.4f}",
        "excess_over_block": f"{excess:.2f}" if excess > 0 else None,
    }
    return ItBlockResult(
        inp.block_key, Decimal(inp.rate_percent), round_half_up(inp.opening_wdv, 2), round_half_up(additions_full, 2),
        round_half_up(additions_half, 2), round_half_up(disposals, 2), depreciation, closing, tuple(flags), details)
