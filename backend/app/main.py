"""FastAPI entry point. One endpoint per module so the frontend can re-request
only the modules whose inputs changed."""
from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .ai.llm import build_facts, generate_comms, parse_description
from .demo_scenarios import demo_scenario_a
from .equipment.rules import equipment
from .graph import edge_info, is_demo, load_graph, snap
from .impact.network import network_impact
from .impact.transit import transit_impact
from .schemas import (
    Comms, CommsRequest, EquipmentRequest, EquipmentResult, NetworkImpact,
    NetworkRequest, ParseRequest, ParseResult, ScenarioParams, SnapRequest, SnapResult,
    TransitImpact, TransitRequest,
)

app = FastAPI(title="Roadworks Impact Simulator", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True, "demo_graph": is_demo()}


@app.get("/api/demo-scenario", response_model=ScenarioParams)
def demo_scenario():
    """MVP scenario: water main replacement near Flemington Rd x Racecourse Rd (values are assumptions)."""
    return demo_scenario_a()


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
