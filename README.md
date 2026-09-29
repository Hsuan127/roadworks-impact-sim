# Roadworks impact preview

FEIT Hackathon 2026 · Future Cities (RPM Hire problem statement).
A planner sets up a road closure, and before anything goes on site sees the knock-on effects on
traffic, pedestrians and public transport, gets an equipment list checked against depot stock,
and drafts VMS messages and a public notice.

## Run it

```bash
# API (Python 3.11+)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # http://127.0.0.1:8000/docs

# Web app (Node 20+), in a second terminal
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

Tests: `cd backend && pytest`.

Without real data the API serves a **demo grid** around the demo site and placeholder transit routes,
so the whole flow works on day one. The UI shows a banner while demo data is in use.

Real streets are **committed** (`backend/app/data/`: OSM drive network within 3 km of the demo site,
walk network within 800 m, facilities, and VicRoads AADT matched to edges), so no one needs osmnx or a
live Overpass call to run the app. To rebuild them (needs internet):

```bash
cd backend
pip install -r requirements-data.txt
python scripts/fetch_osm.py    # drive + walk networks, hospitals/schools
python scripts/fetch_aadt.py   # VicRoads traffic volumes joined to the drive edges
```

Trips are sampled and routed only within `STUDY_RADIUS_M` (2.5 km) of the works. The first request in
a new area builds that area's baseline; the demo site's is built at startup. Tests use the demo grid;
`REAL_DATA=1 pytest` also runs the P2 checks that need the committed network.

GTFS (P3) is not committed: build `backend/app/data/gtfs/` with `scripts/build_gtfs_subset.py`
(see `backend/app/data/README.md`) or ask P3 for the files.

## Architecture

```
React (Vite + TS + react-leaflet)
  └─ one request per module, keyed only by that module's inputs
FastAPI
  ├─ /api/path              map clicks → nearest intersections → closed path along the streets
  ├─ /api/impact/network    P2  traffic + pedestrian impact
  ├─ /api/impact/transit    P3  routes and stops affected
  ├─ /api/equipment         P4  rule-based equipment list + stock + hire cost
  ├─ /api/comms             P5  VMS text + public notice
  └─ /api/parse             P5  one sentence → form pre-fill (optional, needs API key)
```

**Change one field, re-run only what depends on it.** The frontend hook `useModuleResult` caches each
module by its own request body, and the backend caches the expensive routing step by the routing
fields only. Editing the duration re-runs equipment only; the map stays as it is.

| Changed field | Re-runs | Stays cached |
| --- | --- | --- |
| Duration | equipment (cost), comms | network, transit |
| Daily hours | network volume profile (cheap), equipment | shortest-path routing |
| Work zone length | equipment | network, transit |
| What is closed / direction / location | everything | — |

**AI writes words, rules compute numbers.** Quantities come only from `equipment/rules.yaml`.
Public text is built from computed facts; any LLM rewrite containing a number that is not in those
facts is rejected (`passes_number_guard`) and the template is used.

## Who owns what

| Owner | Area | Start here |
| --- | --- | --- |
| P1 | Web app, integration, `schemas.py` ⇄ `types.ts` | `frontend/src/App.tsx` |
| P2 | Network impact, OSM data | `backend/app/impact/network.py`, `scripts/fetch_osm.py` |
| P3 | Public transport, GTFS | `backend/app/impact/transit.py`, `scripts/build_gtfs_subset.py` |
| P4 | Equipment rules, standards, inventory | `backend/app/equipment/rules.yaml`, `inventory.csv` |
| P5 | AI layer, messages, pitch | `backend/app/ai/llm.py` |

## Still to do (search for `TODO`)

- [ ] P3: download Victoria GTFS schedule and run `scripts/build_gtfs_subset.py`
- [ ] P4: replace every `TODO_VERIFY` value in `rules.yaml` from AS 1742.3 / AGTTM, then set `verified: true`
- [ ] P4: replace `inventory.csv` placeholders with RPM Hire's real items and rates (ask the mentors)
- [ ] P5: confirm the VMS board format (lines × characters) with RPM Hire; set `VMS_*` in `config.py`
- [ ] All: confirm lane layout, bike lane and tram position at Flemington Rd × Racecourse Rd

## Limits (say these in the pitch)

- The trip pattern is synthetic. Who travels where is invented; how much traffic a road carries is not.
- Delays come from published VicRoads volumes (2019, the newest year released) through a standard
  BPR capacity curve. The hourly profile is measured from SCATS site 4463, 86 m away; lane
  capacity is still an assumption marked `TODO_VERIFY`, not a measured saturation flow.
- One pass, not a user equilibrium: drivers do not re-choose routes in response to congestion they
  themselves cause. Real assignment iterates; this does not.
- Only roads with a published count get a congestion curve. That is the declared arterial network,
  so dumping traffic into unmeasured back streets is **under**-stated, not over-stated.
- Equipment rules are placeholders until verified; every output is a draft for a qualified practitioner.
- OSM rarely has footpath width or kerb ramps, so walking detours may not be accessible.
