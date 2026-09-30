"""Shared plans: one copy on the server, last write wins, comments pinned to a plan or segment."""
import pytest
from fastapi.testclient import TestClient

from app import plans
from app.main import app

client = TestClient(app)
ANA = {"name": "Ana", "color": "#1D5FD1"}
BEN = {"name": "Ben", "color": "#3C8A2E"}


@pytest.fixture(autouse=True)
def empty():
    plans.clear()
    yield
    plans.clear()


def scenario():
    return client.get("/api/demo-scenario").json()


def test_second_person_adds_a_segment_and_both_see_it():
    s = scenario()
    s["segments"][0]["owner"] = "Ana"
    p = client.post("/api/plans", json={"scenarios": [s], "author": ANA}).json()
    assert p["version"] == 1
    theirs = client.get(f"/api/plans/{p['id']}", params={"who": "Ben", "color": BEN["color"]}).json()
    seg2 = {**theirs["scenarios"][0]["segments"][0], "id": "2", "owner": "Ben", "name": "Ben's block"}
    theirs["scenarios"][0]["segments"].append(seg2)
    saved = client.put(f"/api/plans/{p['id']}", json={"scenarios": theirs["scenarios"], "author": BEN}).json()
    assert saved["version"] == 2
    mine = client.get(f"/api/plans/{p['id']}", params={"who": "Ana", "color": ANA["color"]}).json()
    assert [g["owner"] for g in mine["scenarios"][0]["segments"]] == ["Ana", "Ben"]
    assert mine["updated_by"]["name"] == "Ben"
    assert {v["name"] for v in mine["viewers"]} == {"Ana", "Ben"}


def test_comments_on_a_segment_and_resolving_them():
    p = client.post("/api/plans", json={"scenarios": [scenario()], "author": ANA}).json()
    url = f"/api/plans/{p['id']}/comments"
    c = client.post(url, json={"author": BEN, "segment_id": "1", "text": "Can this start after the school holidays?"}).json()
    client.post(url, json={"author": BEN, "text": "Looks fine overall."})
    got = client.get(url).json()
    assert [x["segment_id"] for x in got] == ["1", None]
    assert client.patch(f"{url}/{c['id']}").json()["resolved"] is True


def test_unknown_plan_is_404():
    assert client.get("/api/plans/nope").status_code == 404
    assert client.post("/api/plans/nope/comments", json={"author": ANA, "text": "hi"}).status_code == 404
