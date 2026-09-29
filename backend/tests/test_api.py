import pytest
from fastapi.testclient import TestClient

from app.ai.llm import passes_number_guard
from app.geo import haversine_m
from app.graph import load_graph
from app.main import app

client = TestClient(app)


def scenario():
    return client.get("/api/demo-scenario").json()


def demo_edges():
    return scenario()["segments"][0]["edges"]


def equipment_request_from_segments(s, segments=None):
    segments = segments or s["segments"]
    return {
        "segments": [
            {
                "id": seg["id"],
                "edges": seg["edges"],
                "targets": seg["targets"],
                "direction": seg["direction"],
                "lanes_closed": seg["lanes_closed"],
                "length_m": seg["length_m"],
                "speed_limit_kmh": seg["speed_limit_kmh"],
                "road_class": seg["road_class"],
            }
            for seg in segments
        ],
        "duration_days": s["duration_days"],
        "time_window": s["time_window"],
        "custom_hours": s["custom_hours"],
        "work_type": s["work_type"],
    }


def network(*segments, time_window="day"):
    """segments: (edges, targets, direction, lanes_closed)"""
    body = [{"id": str(i), "edges": e, "targets": t, "direction": d, "lanes_closed": n}
            for i, (e, t, d, n) in enumerate(segments, 1)]
    return client.post("/api/impact/network", json={"segments": body, "time_window": time_window}).json()


def test_demo_scenario_is_snapped():
    s = scenario()
    seg = s["segments"][0]
    assert len(seg["edges"]) == 1
    assert len(seg["waypoints"]) == 2
    assert round(seg["length_m"]) == 30, "work length comes from the drawn line"
    assert s["duration_days"] == 3


def _along(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def test_path_starts_and_ends_where_the_user_clicked():
    G = load_graph()
    node = lambda r, c: (G.nodes[r * 7 + c]["y"], G.nodes[r * 7 + c]["x"])  # noqa: E731  demo grid, row 3 = Flemington Rd
    start = _along(node(3, 1), node(3, 2), 0.25)  # a quarter into one block
    end = _along(node(3, 3), node(3, 4), 0.5)  # halfway into the block two further along
    p = client.post("/api/path", json={"points": [start, end]}).json()
    assert len(p["edges"]) == 3, "impacts still compute on the whole street segments touched"
    assert all(e1[1] == e2[0] for e1, e2 in zip(p["edges"], p["edges"][1:])), "path must be continuous"
    assert p["road_name"] == "Flemington Road"
    block = haversine_m(*node(3, 1), *node(3, 2))
    assert abs(p["length_m"] - 2.25 * block) < 5, "drawn line is trimmed to the clicks"
    assert haversine_m(*p["geometry"][0], *start) < 1 and haversine_m(*p["geometry"][-1], *end) < 1

    assert network((p["edges"], ["full"], "both", 1))["affected_trips_pct"] > 0


def test_path_is_named_after_the_road_with_most_drawn_length():
    G = load_graph()
    node = lambda r, c: (G.nodes[r * 7 + c]["y"], G.nodes[r * 7 + c]["x"])  # noqa: E731
    start = _along(node(4, 3), node(3, 3), 0.8)  # the last ~60 m of a Racecourse Rd block
    end = _along(node(3, 3), node(3, 4), 0.5)  # then ~150 m along Flemington Rd
    p = client.post("/api/path", json={"points": [start, end]}).json()
    # Whole-edge lengths would pick Racecourse Rd: its block is slightly longer than Flemington Rd's.
    assert p["road_name"] == "Flemington Road"
    assert p["road_class"] == "primary"


def test_clicking_backwards_follows_the_other_direction():
    G = load_graph()
    node = lambda r, c: (G.nodes[r * 7 + c]["y"], G.nodes[r * 7 + c]["x"])  # noqa: E731
    a, b = _along(node(3, 1), node(3, 2), 0.7), _along(node(3, 1), node(3, 2), 0.3)
    p = client.post("/api/path", json={"points": [a, b]}).json()
    assert p["edges"] == [[3 * 7 + 2, 3 * 7 + 1, 0]]
    assert abs(p["length_m"] - 0.4 * haversine_m(*node(3, 1), *node(3, 2))) < 2


def test_single_click_has_no_segment_yet():
    a, _ = scenario()["segments"][0]["waypoints"]
    p = client.post("/api/path", json={"points": [a]}).json()
    assert p["edges"] == [] and p["road_name"] is None and p["geometry"] == []


def test_full_closure_reroutes_and_hits_tram():
    edges = demo_edges()
    net = network((edges, ["full"], "both", 1))
    assert net["affected_trips_pct"] > 0
    assert net["full_closure"] == {"1": True}
    assert net["load_increase"], "detour streets expected"
    tr = client.post("/api/impact/transit", json={"segments": [{"edges": edges, "targets": ["full"]}]}).json()
    assert any(r["mode"] == "tram" and r["needs_replacement"] for r in tr["routes"])


def test_night_is_less_severe_than_day():
    seg = (demo_edges(), ["traffic_lane"], "citybound", 1)
    day, night = network(seg, time_window="day"), network(seg, time_window="night")
    assert night["avg_extra_min"] <= day["avg_extra_min"]


def test_duration_changes_cost_not_quantities():
    seg = {"id": "1", "edges": demo_edges(), "targets": ["traffic_lane", "bike_lane"], "direction": "citybound", "lanes_closed": 1, "length_m": 30,
           "speed_limit_kmh": 60, "road_class": "primary"}
    base = {"segments": [seg], "time_window": "day", "work_type": "excavation"}
    three = client.post("/api/equipment", json={**base, "duration_days": 3}).json()
    four = client.post("/api/equipment", json={**base, "duration_days": 4}).json()
    assert [i["qty"] for i in three["items"]] == [i["qty"] for i in four["items"]]
    assert four["total_cost_aud"] > three["total_cost_aud"]
    assert "Arrow board" in three["shortages"]  # demo inventory has 0 arrow boards on purpose


def test_comms_template_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    c = client.post("/api/comms", json={"scenario": scenario()}).json()
    assert c["generated_by"] == "template"
    # Lines per screen are enforced; the 12-character width is a draft bound that must not cut words.
    assert all(len(m) <= 3 for m in c["vms_messages"])


def test_comms_keeps_each_closure_with_its_road_and_skips_unfinished_segments(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    s = scenario()
    drawn = s["segments"][0]
    drawn.update(targets=["bike_lane"], direction="citybound")
    unfinished = {**drawn, "id": "2", "edges": [], "geometry": [], "waypoints": drawn["waypoints"][:1],
                  "road_name": "Unfinished St", "targets": ["full"], "direction": "outbound"}
    s["segments"].append(unfinished)
    c = client.post("/api/comms", json={"scenario": s}).json()
    notice = c["public_notice_md"]
    assert f"the bike lane on {drawn['road_name']} (citybound)" in notice
    assert "Unfinished St" not in notice and "outbound" not in notice and "full" not in notice
    assert ["ROAD CLOSED", "UNFINISHED ST", "USE DETOUR"] not in c["vms_messages"]


def test_comms_facts_basic_scenario():
    facts = client.post("/api/comms/facts", json={"scenario": scenario()}).json()
    seg = scenario()["segments"][0]

    assert facts["road"] == "Flemington Road"
    assert facts["duration_days"] == 3
    assert facts["closures"] == [
        {
            "segment_id": seg["id"],
            "road": seg["road_name"],
            "closed": ["traffic lane", "bike lane"],
            "direction": "citybound",
        }
    ]
    assert "equipment" not in facts


def test_comms_facts_includes_network_and_transit_facts():
    s = scenario()
    seg = s["segments"][0]
    net = client.post("/api/impact/network", json={
        "segments": [{"id": seg["id"], "edges": seg["edges"], "targets": ["full"], "direction": "both", "lanes_closed": 1}],
        "time_window": "day",
    }).json()
    tr = client.post("/api/impact/transit", json={"segments": [{"edges": seg["edges"], "targets": ["full"]}]}).json()

    facts = client.post("/api/comms/facts", json={"scenario": s, "network": net, "transit": tr}).json()

    assert facts["avg_extra_min"] == round(net["avg_extra_min"])
    assert facts["detour_streets"]
    assert facts["routes"] == [r["short_name"] for r in tr["routes"]]
    assert facts["replacement_needed"] is True


def test_comms_facts_includes_internal_equipment_facts():
    s = scenario()
    eq = client.post("/api/equipment", json=equipment_request_from_segments(s)).json()

    facts = client.post("/api/comms/facts", json={"scenario": s, "equipment": eq}).json()

    assert facts["equipment"]["items"] == eq["items"]
    assert facts["equipment"]["total_cost_aud"] == eq["total_cost_aud"]
    assert facts["equipment"]["shortages"] == eq["shortages"]
    assert facts["equipment"]["warnings"] == eq["warnings"]
    assert facts["equipment"]["rules_verified"] == eq["rules_verified"]
    assert facts["equipment"]["disclaimer"] == eq["disclaimer"]


def test_comms_keeps_public_notice_free_of_equipment_facts(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    s = scenario()
    eq = client.post("/api/equipment", json=equipment_request_from_segments(s)).json()

    comms = client.post("/api/comms", json={"scenario": s, "equipment": eq}).json()

    assert comms["generated_by"] == "template"
    assert comms["vms_messages"]
    assert "Arrow board" not in comms["public_notice_md"]
    assert "Lane closure advance warning" not in comms["public_notice_md"]
    assert str(eq["total_cost_aud"]) not in comms["public_notice_md"]


def test_number_guard():
    facts = {"duration_days": 3, "avg_extra_min": 4}
    assert passes_number_guard("Works run 3 days, allow 4 minutes.", facts)
    assert not passes_number_guard("Works run 5 days.", facts)


def test_lane_closure_does_not_flag_crossing_tram():
    # Flemington Rd segment; demo tram A runs along the crossing Racecourse Rd
    tr = client.post("/api/impact/transit", json={"segments": [{"edges": demo_edges(), "targets": ["traffic_lane"]}]}).json()
    assert "Demo tram A" not in [r["short_name"] for r in tr["routes"]]


def test_vms_road_name_fits():
    from app.ai.llm import vms_road_name
    assert vms_road_name("Flemington Road") == "FLEMINGTON RD"
    assert vms_road_name("Swan Street") == "SWAN ST"


def test_vms_never_cuts_a_long_road_name(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    s = scenario()
    s["segments"][0].update(road_name="Mount Alexander Road", targets=["full"])
    vms = client.post("/api/comms", json={"scenario": s}).json()["vms_messages"]
    assert "MOUNT ALEXANDER RD" in " ".join(line for m in vms for line in m)


def test_lane_or_bike_closure_is_a_work_zone():
    for targets in (["traffic_lane"], ["bike_lane"], ["footpath"]):
        assert network((demo_edges(), targets, "citybound", 1))["full_closure"] == {"1": False}, targets


def _grid_path(a, b):
    G = load_graph()
    node = lambda r, c: (G.nodes[r * 7 + c]["y"], G.nodes[r * 7 + c]["x"])  # noqa: E731
    return client.post("/api/path", json={"points": [node(*a), node(*b)]}).json()


def test_segments_from_the_same_point_are_independent():
    ab = _grid_path((3, 3), (3, 4))  # A-B along Flemington Rd
    ac = _grid_path((3, 3), (2, 3))  # A-C along Racecourse Rd, sharing point A
    net = network((ab["edges"], ["full"], "both", 1), (ac["edges"], ["bike_lane"], "citybound", 1))
    assert net["full_closure"] == {"1": True, "2": False}, "each segment keeps its own status"
    only_ab = network((ab["edges"], ["full"], "both", 1))
    assert net["affected_trips_pct"] == only_ab["affected_trips_pct"], "a bike-lane-only segment doesn't change routing"
    both_full = network((ab["edges"], ["full"], "both", 1), (ac["edges"], ["full"], "both", 1))
    assert both_full["affected_trips_pct"] > only_ab["affected_trips_pct"]


def test_overlapping_segments_take_the_stronger_effect():
    ab = _grid_path((3, 3), (3, 4))["edges"]
    full = network((ab, ["full"], "both", 1))
    overlapped = network((ab, ["traffic_lane"], "citybound", 1), (ab, ["full"], "both", 1))
    assert overlapped["affected_trips_pct"] == full["affected_trips_pct"]


def test_equipment_is_set_up_per_segment():
    seg = {"id": "1", "edges": demo_edges(), "targets": ["traffic_lane"], "direction": "citybound", "lanes_closed": 1,
           "length_m": 30, "speed_limit_kmh": 60, "road_class": "primary"}
    body = {"duration_days": 3, "time_window": "day", "work_type": "non_excavation"}
    one = client.post("/api/equipment", json={**body, "segments": [seg]}).json()
    # Segment 2 was deleted: the list must say "Segment 3", the label the map shows, not "Segment 2".
    two = client.post("/api/equipment", json={**body, "segments": [seg, {**seg, "id": "3"}]}).json()
    assert sum(i["qty"] for i in two["items"]) == 2 * sum(i["qty"] for i in one["items"])
    assert {i["reason"].split(":")[0] for i in two["items"]} == {"Segment 1", "Segment 3"}


def _layout_body(seg, **plan):
    s = seg
    return {"segments": [{"id": s["id"], "geometry": s["geometry"], "edges": s["edges"], "targets": s["targets"],
                          "direction": s["direction"], "lanes_closed": s["lanes_closed"], "length_m": s["length_m"],
                          "speed_limit_kmh": s["speed_limit_kmh"], "road_class": s["road_class"]}],
            "duration_days": 3, "time_window": plan.get("time_window", "night"), "work_type": "excavation"}


def test_map_layout_places_exactly_the_listed_quantities():
    from collections import Counter
    seg = scenario()["segments"][0]
    for direction, targets in (("citybound", ["traffic_lane", "bike_lane"]), ("both", ["full", "footpath"])):
        body = _layout_body({**seg, "direction": direction, "targets": targets})
        listed = Counter()
        for i in client.post("/api/equipment", json=body).json()["items"]:
            listed[i["item_id"]] += i["qty"]
        placed = Counter(p["item_id"] for p in client.post("/api/equipment/layout", json=body).json()["placements"])
        assert placed == listed, direction


def test_map_layout_puts_warning_signs_upstream():
    seg = scenario()["segments"][0]
    placed = client.post("/api/equipment/layout", json=_layout_body(seg)).json()["placements"]
    start, end = seg["geometry"][0], seg["geometry"][-1]
    sign = next(p for p in placed if p["item_id"] == "sign_roadwork_ahead")
    end_sign = next(p for p in placed if p["item_id"] == "sign_end_roadwork")
    # Traffic runs start → end, so the first warning sign is before the start and far from the end.
    assert haversine_m(sign["lat"], sign["lng"], *start) < haversine_m(sign["lat"], sign["lng"], *end)
    assert haversine_m(sign["lat"], sign["lng"], *start) > 60
    assert haversine_m(end_sign["lat"], end_sign["lng"], *end) < haversine_m(end_sign["lat"], end_sign["lng"], *start)
    assert all(not p["in_stock"] for p in placed if p["item_id"] == "arrow_board")


def test_work_zone_slows_trips_that_stay_on_route():
    lane = network((demo_edges(), ["traffic_lane"], "citybound", 1))
    seg = lane["segment_traffic"]["1"]
    assert seg["slowdown_factor"] > 1 and seg["through_trips_pct"] > 0, "traffic still drives through, slower"
    assert lane["slowed_trips_pct"] > 0
    assert lane["rerouted_trips_pct"] + lane["slowed_trips_pct"] == pytest.approx(lane["affected_trips_pct"], abs=0.002)

    full = network((demo_edges(), ["full"], "both", 1))
    assert full["segment_traffic"]["1"] == {"through_trips_pct": 0.0, "slowdown_factor": None}
    assert full["slowed_trips_pct"] == 0 and full["rerouted_trips_pct"] > 0


def test_facility_next_to_the_works_is_flagged(monkeypatch):
    from app.impact import network as net_mod
    from app.schemas import Facility
    lat, lng = scenario()["segments"][0]["geometry"][0]
    monkeypatch.setattr(net_mod, "load_facilities", lambda: [Facility(name="Test hospital", kind="hospital", lat=lat, lng=lng)])
    # A bike-lane closure reroutes nothing, so only the works themselves can put the hospital in range.
    hits = network((demo_edges(), ["bike_lane"], "citybound", 1))["sensitive_facilities"]
    assert [(f["name"], f["near"]) for f in hits] == [("Test hospital", "works")]


def test_osm_lanes_on_a_two_way_street_count_both_directions():
    import networkx as nx
    from app.graph import edge_lanes
    G = nx.MultiDiGraph()
    G.add_edge(1, 2, lanes="2", oneway=False)
    G.add_edge(2, 3, lanes="2", oneway="True")  # graphml text
    G.add_edge(3, 4, lanes=["3", "2"], oneway=True)  # merged OSM ways
    G.add_edge(4, 5)
    assert [edge_lanes(G, e) for e in G.edges(keys=True)] == [1, 2, 3, 1]


def test_closing_the_only_lane_each_way_closes_the_direction():
    side = _grid_path((1, 1), (1, 2))  # Demo Street 1: lanes=2 in OSM terms, one lane each way
    assert network((side["edges"], ["traffic_lane"], "citybound", 1))["full_closure"] == {"1": True}
    assert network((demo_edges(), ["traffic_lane"], "citybound", 1))["full_closure"] == {"1": False}, "2 lanes each way"


@pytest.fixture
def one_way_demo_link():
    """The demo segment, with its Flemington Rd link made one-way for the duration of a test."""
    G = load_graph()
    seg = scenario()["segments"][0]  # before the change: the demo scenario snaps onto the street index
    u, v, _ = seg["edges"][0]
    saved = {k: dict(d) for k, d in G[v][u].items()}
    G.remove_edges_from([(v, u, k) for k in saved])
    try:
        yield seg
    finally:
        for k, d in saved.items():
            G.add_edge(v, u, key=k, **d)


def test_one_way_street_marked_both_has_one_approach(one_way_demo_link):
    from collections import Counter
    seg = one_way_demo_link
    body = _layout_body({**seg, "direction": "both", "targets": ["traffic_lane"], "speed_limit_kmh": 80})
    items = client.post("/api/equipment", json=body).json()["items"]
    assert {i["qty"] for i in items if i["item_id"] in ("vms_board", "arrow_board")} == {1}
    listed = Counter()
    for i in items:
        listed[i["item_id"]] += i["qty"]
    placed = Counter(p["item_id"] for p in client.post("/api/equipment/layout", json=body).json()["placements"])
    assert placed == listed


def test_closure_outside_the_study_area_is_reported(monkeypatch):
    from app.impact import network as net_mod
    G = load_graph()
    cut_off = 0  # a corner of the demo grid, left out of the routed area like a cul-de-sac would be
    monkeypatch.setattr(net_mod, "study_area", lambda G_, edges: frozenset(n for n in G.nodes if n != cut_off))
    corner = _grid_path((0, 0), (0, 1))["edges"]
    net = network((demo_edges(), ["full"], "both", 1), (corner, ["full"], "both", 1), (corner, ["bike_lane"], "citybound", 1))
    assert net["unmodelled_segments"] == ["2"], "the bike-lane segment changes no routing, so nothing is missing"


def test_parse_keeps_only_whitelisted_valid_fields(monkeypatch):
    import json
    from app.ai import llm
    reply = {"fields": {"segments": [], "speed_limit_kmh": 80, "custom_hours": [1, 2], "work_length_m": 50,
                        "duration_days": 5, "targets": ["full"], "lanes_closed": 9, "time_window": "sometimes"},
             "missing": ["start_date", "location"]}
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "_complete", lambda *a, **k: json.dumps(reply))
    r = client.post("/api/parse", json={"text": "anything"}).json()
    assert {k: v for k, v in r["fields"].items() if v is not None} == {"duration_days": 5, "targets": ["full"]}
    assert r["missing"] == ["start_date", "lanes_closed", "time_window"]


def test_closure_that_cuts_off_trips_is_neither_rerouted_nor_slowed():
    # Both streets at a corner of the demo grid, closed both ways: trips to or from the corner have no route left.
    corner = _grid_path((0, 1), (0, 0))["edges"] + _grid_path((0, 0), (1, 0))["edges"]
    r = client.post("/api/impact/network", json={"segments": [
        {"id": "1", "edges": corner, "targets": ["full"], "direction": "both", "lanes_closed": 1}], "time_window": "day"})
    assert r.status_code == 200
    net = r.json()
    cut_off = net["affected_trips_pct"] - net["rerouted_trips_pct"] - net["slowed_trips_pct"]
    assert cut_off > 0.001, "trips with no route are counted as affected, not as rerouted or slowed"
    assert net["slowed_trips_pct"] == 0


def test_path_that_loops_back_is_named_by_drawn_length():
    G = load_graph()
    node = lambda r, c: (G.nodes[r * 7 + c]["y"], G.nodes[r * 7 + c]["x"])  # noqa: E731
    # Round the block and back onto the first Flemington Rd edge: it is listed once but drawn twice.
    points = [_along(node(3, 2), node(3, 3), 0.3), _along(node(3, 3), node(2, 3), 0.5), _along(node(2, 3), node(2, 2), 0.5),
              _along(node(2, 2), node(3, 2), 0.5), _along(node(3, 2), node(3, 3), 0.6)]
    p = client.post("/api/path", json={"points": points}).json()
    assert len(p["edges"]) == 4, "the edge list does not repeat the first edge"
    assert p["road_name"] == "Flemington Road", "1.3 blocks of Flemington Rd beat one block of each other street"


def _vms(seg, network=None):
    body = {"scenario": {**scenario(), "segments": [seg]}, "network": network, "transit": None, "equipment": None}
    return client.post("/api/comms", json=body).json()["vms_messages"]


def test_vms_says_road_closed_when_no_lane_is_left(monkeypatch):
    from app.ai import llm
    monkeypatch.setattr(llm, "llm_available", lambda: False)
    side = {**_grid_path((1, 1), (1, 2)), "id": "1", "targets": ["traffic_lane"], "direction": "citybound", "lanes_closed": 1}
    net = network((side["edges"], ["traffic_lane"], "citybound", 1))
    assert net["full_closure"] == {"1": True}, "one lane each way: closing it closes the direction"
    msgs = _vms(side, net)
    assert "ROAD CLOSED" in " ".join(line for message in msgs for line in message)
    assert "USE DETOUR" not in " ".join(line for message in msgs for line in message)
    assert ["LEFT LANE", "CLOSED AHEAD", "MERGE RIGHT"] not in msgs, "there is no lane to merge into"

    two = {**scenario()["segments"][0], "targets": ["traffic_lane"], "lanes_closed": 2}
    assert ["LEFT LANE", "CLOSED AHEAD", "MERGE RIGHT"] not in _vms(two), "two lanes closed is not 'LEFT LANE'"


def test_parse_reports_an_empty_target_list_as_missing(monkeypatch):
    import json
    from app.ai import llm
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "_complete", lambda *a, **k: json.dumps({"fields": {"targets": [], "duration_days": 2}, "missing": []}))
    r = client.post("/api/parse", json={"text": "anything"}).json()
    assert r["fields"]["targets"] is None and r["missing"] == ["targets"], "[] would close nothing on the segment"


def test_parse_returns_502_when_the_llm_service_fails(monkeypatch):
    from app.ai import llm

    def down(*a, **k):
        raise RuntimeError("provider down")
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "_complete", down)
    assert client.post("/api/parse", json={"text": "anything"}).status_code == 502


def test_map_layout_uses_the_same_full_closure_test_as_network():
    from app.geo import point_segment_distance_m
    G = load_graph()
    node = lambda r, c: (G.nodes[r * 7 + c]["y"], G.nodes[r * 7 + c]["x"])  # noqa: E731
    # One lane each way on Demo Avenue 2, then two each way on Flemington Rd: one closed lane leaves one open.
    p = client.post("/api/path", json={"points": [node(2, 2), node(3, 2), node(3, 3)]}).json()
    seg = {**p, "id": "1", "targets": ["traffic_lane"], "direction": "citybound", "lanes_closed": 1}
    assert network((seg["edges"], ["traffic_lane"], "citybound", 1))["full_closure"] == {"1": False}
    placed = client.post("/api/equipment/layout", json=_layout_body(seg)).json()["placements"]
    zone = [x for x in placed if "work zone" in x["reason"] and x["item_id"] == "cone"]
    line = seg["geometry"]
    off = [min(point_segment_distance_m(x["lat"], x["lng"], a, b) for a, b in zip(line, line[1:])) for x in zone]
    assert zone and min(off) > 1, "a work zone keeps a lane open: cones stand at the lane line, not the centreline"
