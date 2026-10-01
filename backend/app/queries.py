"""Hire queries: the contractor sends a plan, the depot decides (no owner module; P1 wires it).

Stock is deliberately not shown to the planner. Saying "out of stock" while they plan loses the job
before anyone at the depot has weighed it against the others booked for the same days. So the
planner sends a query, and the depot sees each one with what it would take from stock once every
other open query sharing those days is counted too.

In memory only: a restart empties the inbox. Enough for a demo, not for a business.
"""
from __future__ import annotations

import itertools
import threading
from datetime import datetime, timedelta

from .equipment.rules import equipment
from .schemas import HireQuery, QueryRequest, QueryStatus, StockGap

_lock = threading.Lock()
_queries: dict[str, HireQuery] = {}
_ids = itertools.count(1)


def _label(g) -> str:
    return (g.name or "").strip() or g.road_name or f"Segment {g.id}"


def submit(req: QueryRequest) -> HireQuery:
    # Recompute rather than trust the client's copy: the depot decides on the rules' numbers.
    result = equipment(req.equipment)
    s = req.scenario
    drawn = [g for g in s.segments if g.edges]
    with _lock:
        q = HireQuery(
            id=f"Q{next(_ids):03d}",
            submitted_at=datetime.now().astimezone(),
            contact=req.contact,
            segments=[_label(g) for g in drawn],
            road_classes=sorted({g.road_class for g in drawn if g.road_class}),
            start_date=s.start_date,
            end_date=s.start_date + timedelta(days=req.equipment.duration_days - 1),
            time_window=s.time_window,
            items=result.items,
            total_cost_aud=result.total_cost_aud,
        )
        _queries[q.id] = q
    return _with_gaps(q, list(_queries.values()))


def _overlap(a: HireQuery, b: HireQuery) -> bool:
    return a.start_date <= b.end_date and b.start_date <= a.end_date


def _totals(q: HireQuery) -> dict[str, int]:
    """Quantity per item across the whole query: items come one line per segment."""
    out: dict[str, int] = {}
    for i in q.items:
        out[i.item_id] = out.get(i.item_id, 0) + i.qty
    return out


def _with_gaps(q: HireQuery, everyone: list[HireQuery]) -> HireQuery:
    """Stock gaps count every open query that shares a day with this one. Deliberately pessimistic:
    two queries overlapping by one day are treated as needing the kit at the same time."""
    others = [o for o in everyone if o.id != q.id and o.status != "declined" and _overlap(q, o)]
    theirs = [_totals(o) for o in others]
    meta = {i.item_id: i for i in q.items}
    gaps = []
    for item_id, qty in _totals(q).items():
        demand = qty + sum(t.get(item_id, 0) for t in theirs)
        if demand > meta[item_id].stock:
            gaps.append(StockGap(item_id=item_id, name=meta[item_id].name, stock=meta[item_id].stock,
                                 requested=qty, overlapping_demand=demand))
    return q.model_copy(update={"stock_gaps": gaps, "overlaps_with": [o.id for o in others]})


def inbox() -> list[HireQuery]:
    with _lock:
        everyone = list(_queries.values())
    return sorted((_with_gaps(q, everyone) for q in everyone), key=lambda q: q.submitted_at, reverse=True)


def set_status(qid: str, status: QueryStatus) -> HireQuery | None:
    with _lock:
        if qid not in _queries:
            return None
        _queries[qid] = _queries[qid].model_copy(update={"status": status})
        everyone = list(_queries.values())
    return _with_gaps(_queries[qid], everyone)


def clear() -> None:
    """Tests only."""
    with _lock:
        _queries.clear()
