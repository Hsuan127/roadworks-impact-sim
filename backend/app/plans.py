"""Shared plans and comments (no owner module; P1 wires it).

Planning a closure is rarely one person's job: whoever owns the next block adds their segments to
the same plan, and a supervisor comments instead of drawing. This is the lightest thing that shows
that: one plan on the server, last write wins, clients poll. In memory only; a restart forgets.
"""
from __future__ import annotations

import itertools
import secrets
import threading
from datetime import datetime, timedelta

from .schemas import Comment, CommentWrite, Person, SharedPlan, SharedPlanWrite

PRESENCE = timedelta(seconds=8)  # a viewer counts as "here" this long after their last poll

_lock = threading.Lock()
_plans: dict[str, SharedPlan] = {}
_comments: dict[str, list[Comment]] = {}
_seen: dict[str, dict[str, tuple[Person, datetime]]] = {}
_comment_ids = itertools.count(1)


def _now() -> datetime:
    return datetime.now().astimezone()


def _viewers(pid: str) -> list[Person]:
    cutoff = _now() - PRESENCE
    return [p for p, t in _seen.get(pid, {}).values() if t >= cutoff]


def _touch(pid: str, who: Person | None) -> None:
    if who is not None:
        _seen.setdefault(pid, {})[who.name] = (who, _now())


def create(body: SharedPlanWrite) -> SharedPlan:
    with _lock:
        pid = secrets.token_urlsafe(6)
        plan = SharedPlan(id=pid, version=1, scenarios=body.scenarios, updated_by=body.author, updated_at=_now())
        _plans[pid], _comments[pid] = plan, []
        _touch(pid, body.author)
        return plan.model_copy(update={"viewers": _viewers(pid)})


def read(pid: str, who: Person | None = None) -> SharedPlan | None:
    with _lock:
        if pid not in _plans:
            return None
        _touch(pid, who)
        return _plans[pid].model_copy(update={"viewers": _viewers(pid)})


def write(pid: str, body: SharedPlanWrite) -> SharedPlan | None:
    with _lock:
        if pid not in _plans:
            return None
        old = _plans[pid]
        _plans[pid] = SharedPlan(id=pid, version=old.version + 1, scenarios=body.scenarios,
                                 updated_by=body.author, updated_at=_now())
        _touch(pid, body.author)
        return _plans[pid].model_copy(update={"viewers": _viewers(pid)})


def comments(pid: str) -> list[Comment] | None:
    with _lock:
        return None if pid not in _plans else list(_comments[pid])


def add_comment(pid: str, body: CommentWrite) -> Comment | None:
    with _lock:
        if pid not in _plans:
            return None
        c = Comment(**body.model_dump(), id=f"C{next(_comment_ids)}", created_at=_now())
        _comments[pid].append(c)
        return c


def resolve(pid: str, cid: str, resolved: bool) -> Comment | None:
    with _lock:
        for i, c in enumerate(_comments.get(pid, [])):
            if c.id == cid:
                _comments[pid][i] = c.model_copy(update={"resolved": resolved})
                return _comments[pid][i]
        return None


def clear() -> None:
    """Tests only."""
    with _lock:
        _plans.clear(); _comments.clear(); _seen.clear()
