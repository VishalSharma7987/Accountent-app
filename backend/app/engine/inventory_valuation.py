"""Stock valuation (Phase 5, package B): FIFO, weighted average periodic and moving, returns, S-01 chronology check,
register assembly. Pure Python: no DB, web or AI imports. Decimal only; one rounding helper (round_half_up).

Rules of the module (see docs/PHASE5_PLAN.md):
* Valuation is per item; godowns carry quantities only. Transfers never change value.
* Movements are processed in (date, seq) order from the financial-year opening.
* An outward value is rounded half-up to 2 places, except the movement that takes the last unit on hand (or the last
  unit of a FIFO layer): it takes the whole remaining value, so no rounding residue stays behind.
* A return / reversal is valued at the unit cost of the movement it refers to (never the current average).
* An item that cannot be costed (S-01 gap, S-02, S-12, S-14) is left out of the register with its errors: no guess.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal, localcontext

from app.engine.inventory_nrv import closing_stock_rows
from app.engine.inventory_types import (
    INWARD_KINDS,
    OUTWARD_KINDS,
    QTY_PLACES,
    TRANSFER_KINDS,
    ZERO,
    CostedMovement,
    InventoryPolicy,
    Movement,
    MovementKind,
    NegativeStockMode,
    NrvEntry,
    OpeningStock,
    RegisterRow,
    StockError,
    ValuationMethod,
    ValuationResult,
)
from app.engine.money import round_half_up

K = MovementKind
MONEY0 = Decimal("0.00")
_AVG_KINDS = frozenset({K.SALE, K.WRITE_OFF})                 # outward at the running / period average
_CAME_FROM_STOCK = frozenset({K.PURCHASE_RETURN, K.REVERSAL_OUT})   # outward at the cost of the inward it refers to
_BACK_INTO_STOCK = frozenset({K.SALES_RETURN, K.REVERSAL_IN})       # inward at the cost of the outward it refers to


class _Fail(Exception):
    def __init__(self, error: StockError):
        super().__init__(error.message)
        self.error = error


def _qty(q: Decimal) -> str:
    return f"{q:.{QTY_PLACES}f}"


def _d(on: date) -> str:
    return f"{on:%d-%m-%Y}"


def _prorate(value: Decimal, part: Decimal, whole: Decimal) -> Decimal:
    """value x part / whole, half-up to 2 places; the whole quantity takes the whole value."""
    if part == whole:
        return value
    with localcontext() as ctx:
        ctx.prec = 60
        return round_half_up(value * part / whole, 2)


def _is_transfer(m: Movement, by_id: dict) -> bool:
    if m.kind in TRANSFER_KINDS:
        return True
    ref = by_id.get(m.ref_movement_id)
    return m.kind in (K.REVERSAL_IN, K.REVERSAL_OUT) and ref is not None and ref.kind in TRANSFER_KINDS


def _signed(m: Movement) -> Decimal:
    return m.quantity if m.kind in INWARD_KINDS else -m.quantity


def _validate(m: Movement) -> None:
    if m.quantity <= 0 or m.quantity != m.quantity.quantize(Decimal(1).scaleb(-QTY_PLACES)):
        raise _Fail(StockError(
            "S-02", f"Quantity {m.quantity} on {_d(m.date)} must be above zero with at most {QTY_PLACES} decimal places",
            item_id=m.item_id, godown_id=m.godown_id, movement_id=m.movement_id, on_date=m.date))
    if m.kind == K.PURCHASE and (m.value is None or m.value < 0 or m.value != m.value.quantize(MONEY0)):
        raise _Fail(StockError(
            "S-14", f"Purchase on {_d(m.date)} has no valid cost (an amount of 0 or more with at most 2 decimal places is needed)",
            item_id=m.item_id, godown_id=m.godown_id, movement_id=m.movement_id, on_date=m.date))


def _ref(m: Movement, by_id: dict) -> Movement:
    """The movement a return / reversal refers to, with the S-12 checks."""
    ref = by_id.get(m.ref_movement_id)
    if m.kind in _BACK_INTO_STOCK:
        wanted = {K.SALE} if m.kind == K.SALES_RETURN else OUTWARD_KINDS
        what = "sale" if m.kind == K.SALES_RETURN else "outward movement"
    else:
        wanted = {K.PURCHASE} if m.kind == K.PURCHASE_RETURN else INWARD_KINDS
        what = "purchase" if m.kind == K.PURCHASE_RETURN else "inward movement"
    if ref is None or ref.item_id != m.item_id or ref.kind not in wanted or (ref.date, ref.seq) >= (m.date, m.seq):
        raise _Fail(StockError(
            "S-12", f"Return / reversal on {_d(m.date)} must refer to an earlier {what} of the same item",
            item_id=m.item_id, godown_id=m.godown_id, movement_id=m.movement_id, on_date=m.date))
    return ref


class _Run:
    """Result of one method over one list of movements."""

    def __init__(self):
        self.cost: dict = {}
        self.opening = (ZERO, MONEY0)      # state when the window starts
        self.closing = (ZERO, MONEY0)
        self.inward = (ZERO, MONEY0)       # window totals (qty, value)
        self.outward = (ZERO, MONEY0)


def _take(layers: list, qty: Decimal) -> Decimal:
    """Consume `qty` from the oldest layers (layer = [id, qty, value]); returns the cost."""
    total = MONEY0
    for layer in list(layers):
        if qty == 0:
            break
        take = min(qty, layer[1])
        part = layer[2] if take == layer[1] else _prorate(layer[2], take, layer[1])
        layer[1] -= take
        layer[2] -= part
        total += part
        qty -= take
        if layer[1] == 0:
            layers.remove(layer)
    return total


def _fifo(open_q, open_v, moves, by_id, from_date, run: _Run) -> None:
    layers = [["opening", open_q, open_v]] if open_q > 0 else []
    snap = None
    for m in moves:
        if snap is None and m.date >= from_date:
            snap = (sum((x[1] for x in layers), ZERO), sum((x[2] for x in layers), MONEY0))
        if m.kind == K.PURCHASE:
            layers.append([m.movement_id, m.quantity, m.value])
            run.cost[m.movement_id] = m.value
        elif m.kind in _BACK_INTO_STOCK:
            ref = _ref(m, by_id)
            value = _prorate(run.cost[ref.movement_id], m.quantity, ref.quantity)
            layers.append([m.movement_id, m.quantity, value])
            run.cost[m.movement_id] = value
        elif m.kind in _AVG_KINDS:
            run.cost[m.movement_id] = _take(layers, m.quantity)
        else:
            ref = _ref(m, by_id)
            layer = next((x for x in layers if x[0] == ref.movement_id), None)
            if layer is None or layer[1] < m.quantity:
                raise _Fail(StockError(
                    "S-12", f"Return / reversal on {_d(m.date)}: the stock bought on {_d(ref.date)} is no longer fully on hand "
                    "(part of it is already sold); check this return",
                    item_id=m.item_id, godown_id=m.godown_id, movement_id=m.movement_id, on_date=m.date))
            part = layer[2] if m.quantity == layer[1] else _prorate(layer[2], m.quantity, layer[1])
            layer[1] -= m.quantity
            layer[2] -= part
            if layer[1] == 0:
                layers.remove(layer)
            run.cost[m.movement_id] = part
    run.closing = (sum((x[1] for x in layers), ZERO), sum((x[2] for x in layers), MONEY0))
    run.opening = snap if snap is not None else run.closing


def _moving(open_q, open_v, moves, by_id, from_date, run: _Run) -> None:
    q, v = open_q, open_v
    snap = None
    for m in moves:
        if snap is None and m.date >= from_date:
            snap = (q, v)
        if m.kind == K.PURCHASE:
            value = m.value
        elif m.kind in _BACK_INTO_STOCK:
            ref = _ref(m, by_id)
            value = _prorate(run.cost[ref.movement_id], m.quantity, ref.quantity)
        elif m.kind in _AVG_KINDS:
            value = _prorate(v, m.quantity, q)
        else:
            ref = _ref(m, by_id)
            value = v if m.quantity == q else _prorate(run.cost[ref.movement_id], m.quantity, ref.quantity)
        run.cost[m.movement_id] = value
        if m.kind in INWARD_KINDS:
            q, v = q + m.quantity, v + value
        else:
            q, v = q - m.quantity, v - value
    run.closing = (q, v)
    run.opening = snap if snap is not None else run.closing


def _known_value(m: Movement, by_id: dict) -> Decimal | None:
    """Periodic method: the value of a movement whose cost is known without the period average (a purchase, or a
    return / reversal that traces back to one); None when it is valued at the period average (sale, write-off ...)."""
    if m.kind == K.PURCHASE:
        return m.value
    if m.kind in _AVG_KINDS:
        return None
    ref = _ref(m, by_id)
    ref_value = _known_value(ref, by_id)
    return None if ref_value is None else _prorate(ref_value, m.quantity, ref.quantity)


def _periodic(open_q, open_v, moves, by_id, run: _Run) -> None:
    """Weighted average over one period: pool = opening + purchases (+ returns at known cost). Movements valued at the
    period average (sales, write-offs and the returns that trace to them) net off against each other by quantity."""
    q, v = open_q, open_v
    in_q, in_v, out_q, out_v = ZERO, MONEY0, ZERO, MONEY0
    avg_moves = []
    avg_net = ZERO  # outward-at-average quantity minus inward-at-average quantity
    for m in moves:
        value = _known_value(m, by_id)
        if value is None:
            avg_moves.append(m)
            avg_net += -_signed(m)
            continue
        run.cost[m.movement_id] = value
        if m.kind in INWARD_KINDS:
            q, v, in_q, in_v = q + m.quantity, v + value, in_q + m.quantity, in_v + value
        else:
            q, v, out_q, out_v = q - m.quantity, v - value, out_q + m.quantity, out_v + value
    close_q = q - avg_net
    if avg_net != 0 and q <= 0:
        raise _Fail(StockError("S-01", "No stock is available to work out the weighted average cost for this period",
                               item_id=moves[0].item_id))
    if avg_net == 0:
        avg_value = MONEY0
    elif close_q == 0:
        avg_value = v                                  # everything left: the whole remaining value, no residue
    else:
        avg_value = _prorate(v, abs(avg_net), q)
    for m in avg_moves:
        run.cost[m.movement_id] = _prorate(v, m.quantity, q)
    if avg_net > 0:
        out_q, out_v, close_v = out_q + avg_net, out_v + avg_value, v - avg_value
    elif avg_net < 0:
        in_q, in_v, close_v = in_q - avg_net, in_v + avg_value, v + avg_value
    else:
        close_v = v
    run.closing = (close_q, close_v)
    run.inward, run.outward = (in_q, in_v), (out_q, out_v)


def _check_stock(item_moves: list[Movement], godown_open: dict, mode: NegativeStockMode, to_date: date):
    """S-01 over the whole chronology. Returns (errors, item_negative_up_to_to_date)."""
    severity = "error" if mode == NegativeStockMode.BLOCK else "warning"
    on_hand = defaultdict(lambda: ZERO, godown_open)
    errors: list[StockError] = []
    item_negative = False
    for m in item_moves:
        on_hand[m.godown_id] += _signed(m)
        if on_hand[m.godown_id] < 0:
            errors.append(StockError(
                "S-01", f"Stock of item {m.item_id} in godown {m.godown_id} would be {_qty(on_hand[m.godown_id])} on {_d(m.date)}: "
                "more goods leave than were on hand", severity, item_id=m.item_id, godown_id=m.godown_id,
                movement_id=m.movement_id, on_date=m.date))
            if sum(on_hand.values(), ZERO) < 0 and m.date <= to_date:
                item_negative = True
    return errors, item_negative


def _value_item(policy, item_id, from_date, to_date, open_q, open_v, moves, by_id):
    """-> (RegisterRow without godown data, costed movements). Raises _Fail."""
    value_moves = [m for m in moves if not _is_transfer(m, by_id) and m.date <= to_date]
    run = _Run()
    method = policy.method
    if method == ValuationMethod.FIFO:
        _fifo(open_q, open_v, value_moves, by_id, from_date, run)
    elif method == ValuationMethod.WA_MOVING:
        _moving(open_q, open_v, value_moves, by_id, from_date, run)
    else:
        before = [m for m in value_moves if m.date < from_date]
        window = [m for m in value_moves if m.date >= from_date]
        pre = _Run()
        if before:
            _periodic(open_q, open_v, before, by_id, pre)
            run.opening = pre.closing
            run.cost.update(pre.cost)
        else:
            run.opening = (open_q, open_v)
        sub = _Run()
        if window:
            _periodic(run.opening[0], run.opening[1], window, by_id, sub)
            run.cost.update(sub.cost)
            run.closing, run.inward, run.outward = sub.closing, sub.inward, sub.outward
        else:
            run.closing = run.opening
    if method != ValuationMethod.WA_PERIODIC:
        iq, iv, oq, ov = ZERO, MONEY0, ZERO, MONEY0
        for m in value_moves:
            if m.date < from_date:
                continue
            if m.kind in INWARD_KINDS:
                iq, iv = iq + m.quantity, iv + run.cost[m.movement_id]
            else:
                oq, ov = oq + m.quantity, ov + run.cost[m.movement_id]
        run.inward, run.outward = (iq, iv), (oq, ov)
    row = RegisterRow(item_id, run.opening[0], run.opening[1], run.inward[0], run.inward[1], run.outward[0], run.outward[1],
                      run.closing[0], run.closing[1])
    costed = []
    for m in value_moves:
        if m.date < from_date:
            continue
        value = run.cost[m.movement_id]
        costed.append(CostedMovement(m.movement_id, m.seq, m.date, m.item_id, m.godown_id, m.kind, m.quantity, value,
                                     round_half_up(value / m.quantity, 4)))
    for m in moves:  # transfers: quantity only, no value
        if m.date >= from_date and m.date <= to_date and _is_transfer(m, by_id):
            costed.append(CostedMovement(m.movement_id, m.seq, m.date, m.item_id, m.godown_id, m.kind, m.quantity, MONEY0,
                                         Decimal("0.0000")))
    costed.sort(key=lambda c: (c.date, c.seq))
    return row, costed


def compute_valuation(
    policy: InventoryPolicy,
    from_date: date,
    to_date: date,
    opening: list[OpeningStock],
    movements: list[Movement],
    nrv_entries: list[NrvEntry] | None = None,
) -> ValuationResult:
    """Value every item for the window [from_date, to_date].

    `opening` is the financial-year opening; `movements` are all posted movements of the year (the engine ignores the
    ones after `to_date` for value but still checks S-01 on them). Items come out in id order. `closing` (AS 2 rows) is
    filled when `nrv_entries` is given (NRV entered for `to_date`)."""
    items = sorted({o.item_id for o in opening} | {m.item_id for m in movements}, key=str)
    by_id = {m.movement_id: m for m in movements}
    result = ValuationResult(policy, from_date, to_date)
    for item_id in items:
        item_open = [o for o in opening if o.item_id == item_id]
        item_moves = sorted((m for m in movements if m.item_id == item_id), key=lambda m: (m.date, m.seq))
        open_q = sum((o.quantity for o in item_open), ZERO)
        open_v = sum((o.value for o in item_open), MONEY0)
        godown_open: dict = defaultdict(lambda: ZERO)
        for o in item_open:
            godown_open[o.godown_id] += o.quantity
        try:
            for m in item_moves:
                _validate(m)
            if open_q == 0 and open_v != 0 or open_q < 0 or open_v < 0:
                raise _Fail(StockError("S-08", f"Opening stock of item {item_id} must have a quantity and a value of 0 or more, "
                                       "and a value only when there is a quantity", item_id=item_id))
            stock_errors, negative = _check_stock(item_moves, godown_open, policy.negative_stock_mode, to_date)
            result.errors.extend(stock_errors)
            if negative:
                if policy.negative_stock_mode == NegativeStockMode.WARN:
                    result.errors.append(StockError(
                        "S-01", f"Item {item_id} goes below zero stock, so its cost cannot be worked out; it is left out",
                        item_id=item_id))
                continue
            row, costed = _value_item(policy, item_id, from_date, to_date, open_q, open_v, item_moves, by_id)
        except _Fail as fail:
            result.errors.append(fail.error)
            continue
        by_godown = defaultdict(lambda: ZERO, godown_open)
        for m in item_moves:
            if m.date <= to_date:
                by_godown[m.godown_id] += _signed(m)
        row = RegisterRow(**{**row.__dict__, "by_godown_qty": dict(by_godown)})
        result.register.append(row)
        result.costed.extend(costed)
    if nrv_entries is not None:
        rows, errs = closing_stock_rows(result.register, nrv_entries, to_date)
        result.closing.extend(rows)
        result.errors.extend(errs)
    return result
