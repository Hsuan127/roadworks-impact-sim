"""Hire queries: the planner never sees stock; the depot sees gaps across overlapping queries."""
import pytest
from fastapi.testclient import TestClient

from app import queries
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def empty_inbox():
    queries.clear()
    yield
    queries.clear()


def body(start="2026-10-06", days=3, company="Acme Civil", name=None):
    s = client.get("/api/demo-scenario").json()
    s["start_date"], s["duration_days"] = start, days
    g = s["segments"][0]
    g["name"] = name
    seg = {k: g[k] for k in ("id", "edges", "targets", "direction", "lanes_closed", "length_m",
                             "speed_limit_kmh", "road_class")}
    eq = {"segments": [seg], "duration_days": days, "time_window": "day", "work_type": "excavation"}
    return {"scenario": s, "equipment": eq, "contact": {"company": company, "contact": "Sam"}}


def test_query_is_recomputed_and_dated():
    q = client.post("/api/queries", json=body(name="Water main pit")).json()
    assert q["status"] == "new"
    assert q["segments"] == ["Water main pit"], "the planner's segment name reaches the depot"
    assert q["start_date"] == "2026-10-06" and q["end_date"] == "2026-10-08", "end date is inclusive"
    expected = client.post("/api/equipment", json=body()["equipment"]).json()
    assert q["total_cost_aud"] == expected["total_cost_aud"]


def test_overlapping_queries_add_up_against_stock():
    one = client.post("/api/queries", json=body()).json()
    solo = {g["item_id"]: g for g in one["stock_gaps"]}
    client.post("/api/queries", json=body(start="2026-10-08", company="Other Co"))  # shares 8 Oct
    client.post("/api/queries", json=body(start="2026-11-01", company="Later Co"))  # no shared day
    inbox = {q["contact"]["company"]: q for q in client.get("/api/queries").json()}
    acme = inbox["Acme Civil"]
    assert acme["overlaps_with"] == [inbox["Other Co"]["id"]]
    assert inbox["Later Co"]["overlaps_with"] == []
    for g in acme["stock_gaps"]:
        assert g["overlapping_demand"] == 2 * g["requested"]
        assert g["overlapping_demand"] > g["stock"]
    assert len(acme["stock_gaps"]) >= len(solo), "a second overlapping job can only widen the gaps"


def test_declined_query_frees_its_stock():
    a = client.post("/api/queries", json=body()).json()
    b = client.post("/api/queries", json=body(company="Other Co")).json()
    assert client.patch(f"/api/queries/{b['id']}", json={"status": "declined"}).json()["status"] == "declined"
    acme = next(q for q in client.get("/api/queries").json() if q["id"] == a["id"])
    assert acme["overlaps_with"] == []


def test_unknown_query_is_404():
    assert client.patch("/api/queries/Q999", json={"status": "accepted"}).status_code == 404
