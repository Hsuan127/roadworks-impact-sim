"""FastAPI entry point. One endpoint per module so the frontend can re-request
only the modules whose inputs changed."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .ai.llm import build_facts, generate_comms, parse_description
from .equipment.rules import equipment
from .graph import edge_info, is_demo, load_graph, snap
from .impact.network import network_impact
from .impact.transit import transit_impact
from .schemas import (
    ClosureTarget, Comms, CommsRequest, EquipmentRequest, EquipmentResult, Location, NetworkImpact,
    NetworkRequest, ParseRequest, ParseResult, ScenarioParams, SnapRequest, SnapResult, TimeWindow,
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
    lat, lng = config.DEMO_WORK_POINT
    edge = snap(lat, lng)
    info = edge_info(load_graph(), edge)
    today = date.today()
    next_tue = today + timedelta(days=(1 - today.weekday()) % 7 or 7)
    return ScenarioParams(
        name="A",
        location=Location(lat=lat, lng=lng, edge=edge, road_name=info["road_name"], road_class=info["road_class"]),
        targets=[ClosureTarget.traffic_lane, ClosureTarget.bike_lane],
        direction="citybound", lanes_closed=1, work_length_m=30,
        start_date=next_tue, duration_days=3, time_window=TimeWindow.day,
        speed_limit_kmh=info["speed_limit_kmh"], work_type=WorkType.excavation,
    )


@app.get("/api/map-center")
def map_center():
    return {"lat": config.DEMO_CENTER[0], "lng": config.DEMO_CENTER[1]}


@app.post("/api/snap", response_model=SnapResult)
def snap_point(req: SnapRequest):
    edge = snap(req.lat, req.lng)
    info = edge_info(load_graph(), edge)
    return SnapResult(edge=edge, road_name=info["road_name"], lat=req.lat, lng=req.lng,
                      speed_limit_kmh=info["speed_limit_kmh"], road_class=info["road_class"], geometry=info["geometry"])


@app.post("/api/impact/network", response_model=NetworkImpact)
def impact_network(req: NetworkRequest):
    return network_impact(req)


@app.post("/api/impact/transit", response_model=TransitImpact)
def impact_transit(req: TransitRequest):
    return transit_impact(req)


@app.post("/api/equipment", response_model=EquipmentResult)
def equipment_list(req: EquipmentRequest):
    return equipment(req)


@app.post("/api/comms", response_model=Comms)
def comms(req: CommsRequest):
    return generate_comms(req)


@app.post("/api/comms/facts")
def comms_facts(req: CommsRequest):
    return build_facts(req)


@app.post("/api/parse", response_model=ParseResult)
def parse(req: ParseRequest):
    try:
        return parse_description(req.text, date.today().isoformat())
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Could not read the model's answer: {e}") from e
