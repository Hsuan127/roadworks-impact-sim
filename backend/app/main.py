"""FastAPI entry point. One endpoint per module so the frontend can re-request
only the modules whose inputs changed."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .ai.llm import generate_comms, parse_description
from .equipment.layout import equipment_layout
from .equipment.rules import equipment
from .geo import locate_on_polyline, polyline_length_m, slice_polyline
from .graph import edge_info, is_demo, load_graph, plan_path, snap
from .impact.network import network_impact
from .impact.transit import transit_impact
from .schemas import (
    ClosureTarget, Comms, CommsRequest, EquipmentLayout, EquipmentRequest, EquipmentResult, LayoutRequest, NetworkImpact,
    NetworkRequest, ParseRequest, ParseResult, PathRequest, PathResult, ScenarioParams, Segment, TimeWindow,
    TransitImpact, TransitRequest, WorkType,
)

app = FastAPI(title="Roadworks Impact Simulator", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True, "demo_graph": is_demo()}


@app.get("/api/demo-scenario", response_model=ScenarioParams)
def demo_scenario():
    """MVP scenario: water main replacement near Flemington Rd x Racecourse Rd (values are assumptions)."""
    G = load_graph()
    edge = snap(*config.DEMO_WORK_POINT)
    geom = edge_info(G, edge)["geometry"]
    mid = locate_on_polyline(geom, *config.DEMO_WORK_POINT)
    ends = slice_polyline(geom, mid - 15, mid + 15)  # a 30 m work zone
    p = _path([ends[0], ends[-1]])
    today = date.today()
    next_tue = today + timedelta(days=(1 - today.weekday()) % 7 or 7)
    return ScenarioParams(
        name="A",
        segments=[Segment(
            id="1", waypoints=p.waypoints, edges=p.edges, geometry=p.geometry, length_m=p.length_m,
            road_name=p.road_name, road_class=p.road_class, speed_limit_kmh=p.speed_limit_kmh,
            targets=[ClosureTarget.traffic_lane, ClosureTarget.bike_lane], direction="citybound", lanes_closed=1,
        )],
        start_date=next_tue, duration_days=3, time_window=TimeWindow.day, work_type=WorkType.excavation,
    )


@app.get("/api/map-center")
def map_center():
    return {"lat": config.DEMO_CENTER[0], "lng": config.DEMO_CENTER[1]}


def _path(points: list[tuple[float, float]]) -> PathResult:
    G = load_graph()
    waypoints, edges, line = plan_path(points)
    # Name the path after the road with the most length on it; ties go to the first one clicked.
    length_by_name: dict[str | None, float] = {}
    for e in edges:
        name = edge_info(G, e)["road_name"]
        length_by_name[name] = length_by_name.get(name, 0.0) + G.edges[e]["length"]
    main = max(length_by_name, key=length_by_name.__getitem__) if edges else None
    info = edge_info(G, next(e for e in edges if edge_info(G, e)["road_name"] == main)) if edges else {}
    return PathResult(
        waypoints=waypoints, edges=edges, geometry=line, length_m=round(polyline_length_m(line), 1),
        road_name=info.get("road_name"), road_class=info.get("road_class"), speed_limit_kmh=info.get("speed_limit_kmh"),
    )


@app.post("/api/path", response_model=PathResult)
def path(req: PathRequest):
    """Clicks anywhere along streets → the drawn line between them, plus the street segments it touches."""
    try:
        return _path(req.points)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.post("/api/impact/network", response_model=NetworkImpact)
def impact_network(req: NetworkRequest):
    return network_impact(req)


@app.post("/api/impact/transit", response_model=TransitImpact)
def impact_transit(req: TransitRequest):
    return transit_impact(req)


@app.post("/api/equipment", response_model=EquipmentResult)
def equipment_list(req: EquipmentRequest):
    return equipment(req)


@app.post("/api/equipment/layout", response_model=EquipmentLayout)
def equipment_on_map(req: LayoutRequest):
    return equipment_layout(req)


@app.post("/api/comms", response_model=Comms)
def comms(req: CommsRequest):
    return generate_comms(req)


@app.post("/api/parse", response_model=ParseResult)
def parse(req: ParseRequest):
    try:
        return parse_description(req.text, date.today().isoformat())
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Could not read the model's answer: {e}") from e
