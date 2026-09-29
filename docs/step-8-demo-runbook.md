# Step 8 Demo Runbook

## Start

Backend:

```bash
cd backend
LLM_PROVIDER=none uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm run dev
```

Keep `LLM_PROVIDER=none` for rehearsals when you need deterministic template-only output. If Gemini is enabled and fails with a 429/503/network error, P5 falls back to the same deterministic public notice template.

## Demo Order

Start with Scenario A from `/api/demo-scenario`: Flemington Road citybound lane plus bike lane closure, 3 day daytime excavation from 2026-10-06. It is the lowest-risk baseline, matches the default frontend form, and is the only fixed scenario currently exposed by the UI path.

Use the fixed backend scenarios for broader coverage in backend tests or when manually recreating/calling the payloads through the API:

- Scenario A: Flemington Road lane plus bike lane closure.
- Scenario B: Flemington Road full closure in both directions, showing tram impact and possible replacement services.
- Scenario C: Racecourse Road night works with traffic lane plus footpath impacts, heavier equipment, and transit impact.

## Click Sequence

1. Load the frontend and keep the default Scenario A.
2. Point at P2 traffic impact: affected trips, extra minutes, detour/load streets, and demo-data note.
3. Point at P3 transit impact: affected routes/stops and replacement-service flag where relevant.
4. Point at P4 equipment: quantities, shortages, total cost, and rules disclaimer.
5. Open P5 communications: VMS messages and public notice.
6. For API verification, request `/api/comms/facts` with the same scenario, network, transit, and equipment payload to show the facts P5 is allowed to use.

## Say Aloud

- Equipment inventory and rules are placeholders pending verification against AS 1742.3 / AGTTM.
- VMS uses the current draft 3 x 12 character limit; this is marked `TODO_VERIFY`.
- Road graph, synthetic trips, facilities, and demo transit may be placeholder data when real local datasets are not loaded.
- Public notices intentionally exclude internal equipment quantities, costs, stock, and rule reasons.
