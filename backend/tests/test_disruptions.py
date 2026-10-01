"""Nearby planned works: time overlap, ranking, and what happens without the snapshot.

Overlap and ranking use hand-made permits, so they run anywhere. The default run has no data dir
(conftest.py), which is exactly the missing-snapshot case the endpoint must report honestly.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import config
from app.impact.disruptions import level, overlap, work_hours
from app.main import app
from app.schemas import TimeWindow

MON = date(2026, 10, 12)  # a Monday
DAY, NIGHT = work_hours(TimeWindow.day, None), work_hours(TimeWindow.night, None)


def permit(shifts, start="2026-10-01T00:00+11:00", end="2026-12-01T00:00+11:00"):
    return {"start": start, "end": end, "shifts": shifts}


def nightly(weekdays=range(7)):  # 21:00-05:00, as most permits near the demo site
    return [{"weekday": w, "start_h": 21.0, "hours": 8.0} for w in weekdays]


def test_work_hours():
    assert DAY == (9.5, 15.5)
    assert NIGHT == (20.0, 29.0)  # runs past midnight
    assert work_hours(TimeWindow.custom, (22, 6)) == (22.0, 30.0)
    assert work_hours(TimeWindow.custom, (10, 14)) == (10.0, 14.0)


def test_night_permit_meets_night_works_not_day_works():
    p = permit(nightly())
    assert overlap(p, MON, 3, DAY) == 0
    assert overlap(p, MON, 3, NIGHT) == 8 / 9  # 21:00-05:00 inside our 20:00-05:00


def test_only_listed_weekdays_count():
    p = permit(nightly(weekdays=[0]))  # Monday nights only
    assert round(overlap(p, MON, 3, NIGHT), 3) == round(8 / 27, 3)  # one of our three nights


def test_overnight_shift_from_the_day_before_counts():
    p = permit([{"weekday": 6, "start_h": 22.0, "hours": 12.0}])  # Sunday 22:00 to Monday 10:00
    assert overlap(p, MON, 1, DAY) == 0.5 / 6  # Monday 09:30-10:00


def test_permit_period_clips_the_shifts():
    p = permit(nightly(), start="2026-10-13T00:00+11:00")  # starts at midnight during our first night
    assert round(overlap(p, MON, 3, NIGHT), 3) == round((5 + 8 + 8) / 27, 3)  # first night from 00:00 only
    assert overlap(permit(nightly(), end="2026-10-01T00:00+11:00", start="2026-09-01T00:00+11:00"), MON, 3, NIGHT) == 0


def test_repeated_shifts_are_not_double_counted():
    p = permit(nightly() + nightly())
    assert overlap(p, MON, 3, NIGHT) == 8 / 9


def test_no_published_hours_counts_the_whole_period():
    assert overlap(permit(None), MON, 3, DAY) == 1  # cannot be ruled out, so not hidden


def test_levels():
    assert level(0, 0) == 0  # not at the same time, however close
    assert level(1, 1) == 3
    assert level(1, 0.3) == 2
    assert level(1, 0.1) == 1


@pytest.mark.skipif((config.DATA_DIR / "disruptions.json").exists(), reason="the snapshot is present")
def test_endpoint_without_snapshot_invents_nothing():
    r = TestClient(app).post("/api/disruptions", json={
        "works": [[-37.7945, 144.9504]], "start_date": "2026-10-12", "duration_days": 3, "time_window": "night",
    }).json()
    assert r["available"] is False
    assert r["disruptions"] == []
