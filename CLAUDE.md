# CLAUDE.md — context for AI assistants working in this repo

Roadworks impact preview. FEIT Hackathon 2026 (University of Melbourne), Future Cities theme,
RPM Hire problem statement: a planner sets up a road closure and sees the knock-on effects on
traffic, pedestrians and public transport before anything goes on site, using typical traffic
equipment inventory. The system also generates equipment lists and drafts VMS messages and
public notices.

Team of 5, about 8 hours of build time over 2 days. Team docs are written in Traditional Chinese;
code, identifiers and commit messages stay in English.

## Commands

### Development
```bash
# Backend (Python 3.11+, from backend/)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # API on :8000, docs at http://127.0.0.1:8000/docs

# Frontend (Node 20+, from frontend/, separate terminal)
npm install
npm run dev                            # UI on :5173 (proxies /api to 127.0.0.1:8000)
npm run build                          # type-check + build

# Tests
cd backend && pytest -q                # must stay green before every commit
pytest tests/test_api.py -k test_comms # single test
```

### Environment setup
Copy `.env.example` to `backend/.env` and optionally set `ANTHROPIC_API_KEY` to enable AI features
(one-sentence pre-fill and LLM-generated public notices). Without the key the app still runs; P5
falls back to templates.

## Architecture (decided — do not reintroduce Streamlit)

- Frontend: React 18 + Vite + TypeScript + react-leaflet. Streamlit was dropped because
  streamlit-folium was not stable enough.
- Backend: FastAPI, one endpoint per module so the UI re-requests only what changed.

### Module-based request architecture
**Critical design principle**: the frontend requests each module independently, keyed ONLY by that
module's specific inputs. This enables surgical cache invalidation — changing a field re-runs only
the modules that depend on it.

Example: editing `duration_days` re-runs equipment (cost changes) but NOT network or transit
(routing stays the same).

Implementation:
- `frontend/src/hooks/useScenarioResults.ts` — builds each module's request body from only the
  fields that module uses.
- `frontend/src/hooks/useModuleResult.ts` — caches each module by `url + JSON.stringify(body)`.
- Backend `@lru_cache` decorators cache expensive operations by routing-relevant fields only
  (`_routing_impact` in `backend/app/impact/network.py:158`).

### Request minimality contract
Each module's request schema includes ONLY the fields that affect its computation:
- `NetworkRequest` (`backend/app/schemas.py:78`): excludes `duration_days`, `work_length_m` —
  these don't change routing.
- `EquipmentRequest` (`backend/app/schemas.py:144`): includes `duration_days` because it affects
  rental cost.

**When adding fields**: add to a module's request schema ONLY if changing that field should trigger
recomputation.

### API endpoints
```
/api/snap              - Map click → nearest street segment
/api/impact/network    - P2: Traffic + pedestrian impact (synthetic trip-based)
/api/impact/transit    - P3: Affected routes and stops (GTFS-based)
/api/equipment         - P4: Rule-based equipment list + stock + hire cost
/api/comms             - P5: VMS text + public notice (template or LLM)
/api/parse             - P5: One sentence → form pre-fill (requires API key)
```

## Rules that must not be broken

1. **AI writes words, rules compute numbers.** No LLM output may decide a quantity, delay or cost.
   Public text is built from `CommsFacts`; `passes_number_guard` (`backend/app/ai/llm.py`) rejects
   any LLM rewrite containing a number not present in the facts, and the template is used instead.
   All numbers come from the rule-based modules (P2/P3/P4).
2. **Schema changes touch three places in one commit:** `backend/app/schemas.py`,
   `frontend/src/types.ts`, and the relevant doc under `docs/api/` (check `P5-AI-layer.md` for any
   field marked "P5 reads: yes").
3. **Change one field, recompute only what depends on it.** See the request minimality contract
   above. Duration must never trigger a network recompute. Daily hours now re-run only the cheap
   volume-profile lookup, never the routing (`_routing_impact` is keyed without the time window).
4. **Placeholders are labelled.** Values marked `TODO_VERIFY` (`rules.yaml`, `config.py`) are not
   engineering guidance. Keep `verified: false` until each is checked against AS 1742.3 / AGTTM and
   the clause is recorded in `source`.
5. **Demo data is labelled.** Without `backend/app/data/graph_drive.graphml` and `data/gtfs/`, the
   API serves a demo grid and demo routes and returns `is_demo_data: true`; the UI shows a banner.
6. **Honesty in outputs.** The trip pattern is synthetic; the traffic volumes are not (VicRoads
   AADT). Delay comes from a BPR capacity curve over those volumes, one pass, and only on roads
   with a published count -- so back-street impact is under-stated. Never report a saturation
   constant as if it were a measurement, and never invent a volume for a road that has none.
   Every generated message carries the "draft, needs qualified sign-off" disclaimer.

### Traffic volumes (P2)

`backend/app/data/aadt_by_edge.json` maps OSM edges to published VicRoads counts
(`scripts/fetch_aadt.py`), 2019 being the newest year released. These are **display-only** and
deliberately absent from P5's `CommsFacts`, so `passes_number_guard` rejects any notice quoting them.

SCATS 15-minute counts are usable too. The site coordinates are published separately as **"Victorian
Traffic Signals"** (`SITE_NO`/`LATITUDE`/`LONGITUDE`), *not* inside the volume package — an earlier
note in this repo wrongly concluded SCATS could not be geolocated. Site **4463
FLEMINGTON/ABBOTSFORD** is 86 m from the demo work point, and its March 2026 weekday counts match
the 2019 AADT to within 1 % in both directions (25,568 vs 25,365 citybound; 23,110 vs 23,011
outbound). That agreement is what validates the edge join.

`config.AADT_HOURLY_FRACTION` is measured from those counts, for the windows the regulations
actually impose — day 09:30–15:30 (DTP arterial off-peak) 1,436 veh/h, night 20:00–05:00 374 veh/h,
AM peak 07:30–08:30 2,437 veh/h. Peak is **directional**: citybound AM carries 2,437 veh/h against
outbound's 905, so a single flat peak factor is wrong by 2.7x. Measured for this site and direction
only; lane capacity remains a `TODO_VERIFY` assumption.

## Data flow

1. Demo mode: without real OSM/GTFS data, the API serves a synthetic grid + placeholder routes
   (responses carry `is_demo_data: true`).
2. Real data (done for P2, committed so no one needs osmnx or a live Overpass call):
   - `scripts/fetch_osm.py` → `graph_drive.graphml` (3 km drive, ~5.1k nodes / 10.6k edges),
     `graph_walk.graphml` (800 m walk), `facilities.json`, `meta.json`
   - `scripts/fetch_aadt.py` → `aadt_by_edge.json` (2,969 edges matched to VicRoads counts)
   - `scripts/build_gtfs_subset.py` → `data/gtfs/*.txt` (P3, still to do)

## Module ownership

| Owner | Area | Entry point |
|-------|------|-------------|
| P1 | Web app, integration, keeps `schemas.py` and `types.ts` in sync | `frontend/src/App.tsx` |
| P2 | Network impact, OSM data | `backend/app/impact/network.py` |
| P3 | Public transport, GTFS | `backend/app/impact/transit.py` |
| P4 | Equipment rules, inventory | `backend/app/equipment/rules.yaml`, `inventory.csv`, `rules.py` |
| P5 | AI layer, messages | `backend/app/ai/llm.py`, contract in `docs/api/P5-AI-layer.md` |

## Key files

### Backend
- `app/main.py` — FastAPI entry point, one endpoint per module
- `app/schemas.py` — single source of truth for data contracts
- `app/config.py` — tunable parameters (many marked TODO_VERIFY)
- `app/equipment/rules.yaml` — equipment calculation rules (placeholders until verified)
- `app/equipment/inventory.csv` — stock levels and hire rates (placeholder data)

### Frontend
- `src/types.ts` — mirror of backend schemas
- `src/hooks/useScenarioResults.ts` — per-module request bodies
- `src/hooks/useModuleResult.ts` — module-level caching logic
- `src/App.tsx` — main integration point

### Documentation
- `docs/api/P5-AI-layer.md` — detailed P5 interface spec (in Chinese), defines AI safety rules and
  data contracts

## Testing

Coverage includes:
- Number guard validation (P5)
- Parse field whitelisting (P5)
- Module integration (all endpoints)

## Demo scenario (MVP)

Water main replacement, Flemington Rd citybound near Racecourse Rd (North Melbourne / Parkville),
30 m work zone, 3 days, closing the kerb lane and bike lane. Chosen because RACV/NTRO list the
Flemington Rd x Racecourse Rd intersection among Melbourne's most dangerous, with trams, buses,
bikes and cars competing, next to the Parkville hospital precinct.
Plan A = weekday off-peak; Plan B = copy of A with night hours. Demo beat: change duration 3 → 4 days
and show that only equipment cost and notice dates update.
Validation idea: compare our detours with the official detours for the Eastern Freeway closure
(Chandler Hwy to Tram Rd, 11–14 Sep 2026).

## Input design (decided)

The parameter form is the primary input; every field is independently editable. The one-sentence
input only pre-fills the form (whitelisted, validated fields). Location and speed limit are never
pre-filled; the user confirms location on the map.

## Configuration notes

VMS board format (`backend/app/config.py`):
- `VMS_LINES = 3`, `VMS_CHARS_PER_LINE = 12` are placeholders pending RPM Hire confirmation.
- VMS messages are ALWAYS template-generated (never LLM) to guarantee format compliance.

## Important constraints

From the README "Limits" section — acknowledged system limitations, not bugs:
- The trip pattern is synthetic. Who travels where is invented; how much traffic a road carries
  is not — that comes from published VicRoads counts.
- Delay is one pass of a BPR capacity curve, not a user equilibrium: drivers do not re-choose
  routes in response to congestion they cause. Only roads with a published count get a curve,
  so traffic pushed into unmeasured back streets is **under**-stated.
- Equipment rules are placeholders until verified against standards.
- OSM rarely has footpath width/kerb ramps, so walking detours may not be accessible.

## Research findings not yet in code

Work hours for the demo site (public sources, to be confirmed with the RPM Hire mentor):
- Flemington Rd is an arterial road: consent from the Department of Transport and Planning (DTP),
  Memorandum of Authorisation, DTP-accredited traffic management company.
- Traffic limit: arterial lane closures are typically off-peak only, about 9:30am–3:30pm
  (industry blog, not an official rule). City of Melbourne standard conditions: traffic management
  setups must be outside peak times; the council sets permitted closure times per application.
- Noise limit: EPA Victoria normal working hours 7am–6pm Mon–Fri, 7am–1pm Sat; out-of-hours works
  need justification. City of Melbourne conditions: noisy works supported only until 10pm.
- Consequence: Plan B (night excavation) conflicts with the noise limit and would need an
  out-of-hours permit. Planned feature: warn on time windows that break these limits. Note the
  standard 20:00-05:00 night shift now modelled as Plan B straddles the 22:00 cutoff, so the warning
  would fire on the demo scenario itself.
- City of Melbourne conditions also say: footpaths keep >= 1200 mm clear width outside the CBD;
  "END BICYCLE LANE" signage is not supported (retain, merge into the adjacent lane, or divert);
  keep a shared lane >= 4.0 m past the worksite. The current `sign_bike_lane_closed` rule in
  `rules.yaml` conflicts with this and should change.
- Source: City of Melbourne, "Standard conditions for consent to temporary road or footpath closures"
  (traffic-management-plan-standard-conditions.pdf, 2025).

## Open questions for the RPM Hire mentor

- Typical DTP-approved hours on Flemington Rd; how often night excavation gets out-of-hours approval;
  whether tram corridors add their own restricted windows.
- Real equipment items, stock and daily hire rates; VMS board format (lines x characters).
- Whether Victoria currently applies AS 1742.3 or Austroads AGTTM (+ VIC supplement).

## Working with Claude.ai

Design discussion happens in a Claude.ai chat, which cannot push to GitHub. Changes from there arrive
as `git format-patch` files applied with `git am <file>.patch`. When a patch conflicts, prefer the
version in this repo and reapply the patch's intent by hand.
