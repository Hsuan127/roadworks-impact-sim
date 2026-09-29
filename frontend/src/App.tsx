import { useEffect, useState } from "react";
import { get, post } from "./api";
import CommsPanel from "./components/CommsPanel";
import CompareView from "./components/CompareView";
import MapView from "./components/MapView";
import ResultsPanel from "./components/ResultsPanel";
import ScenarioForm from "./components/ScenarioForm";
import { useScenarioResults } from "./hooks/useScenarioResults";
import type { ScenarioParams, SnapResult } from "./types";

export default function App() {
  const [center, setCenter] = useState<[number, number] | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioParams[]>([]);
  const [active, setActive] = useState(0);
  const [comparing, setComparing] = useState(false);
  const [demoData, setDemoData] = useState(false);
  const [warming, setWarming] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      get<{ lat: number; lng: number }>("/api/map-center"),
      get<ScenarioParams>("/api/demo-scenario"),
      get<{ demo_graph: boolean; baseline_ready: boolean }>("/api/health"),
    ])
      .then(([c, s, h]) => {
        setCenter([c.lat, c.lng]);
        setScenarios([s]);
        setDemoData(h.demo_graph);
        setWarming(!h.baseline_ready);
      })
      .catch(() => setLoadError("Can't reach the API on port 8000. Start it with: uvicorn app.main:app --reload"));
  }, []);

  // The routing baseline takes ~15 s to build on the real graph and is warmed at startup. Poll
  // until it lands so a cold start reads as "warming", not as a hang.
  useEffect(() => {
    if (!warming) return;
    const t = setInterval(() => {
      get<{ baseline_ready: boolean }>("/api/health")
        .then((h) => h.baseline_ready && setWarming(false))
        .catch(() => undefined);
    }, 1500);
    return () => clearInterval(t);
  }, [warming]);

  // Hooks are always called for two slots; slot B is idle until a second plan exists.
  const resultsA = useScenarioResults(scenarios[0] ?? null);
  const resultsB = useScenarioResults(scenarios[1] ?? null);
  const results = [resultsA, resultsB];
  const current = scenarios[active] ?? null;

  const update = (patch: Partial<ScenarioParams>) =>
    setScenarios((all) => all.map((s, i) => (i === active ? { ...s, ...patch } : s)));

  async function pick(lat: number, lng: number) {
    const snapped = await post<SnapResult>("/api/snap", { lat, lng });
    update({
      location: { lat, lng, edge: snapped.edge, road_name: snapped.road_name, road_class: snapped.road_class },
      speed_limit_kmh: snapped.speed_limit_kmh,
    });
  }

  function addPlanB() {
    setScenarios((all) => [all[0], { ...all[0], name: "B" }]);
    setActive(1);
  }

  if (loadError) return <main className="empty"><p>{loadError}</p></main>;
  if (!center || !current) return <main className="empty"><p>Loading the network…</p></main>;

  return (
    <div className="app">
      <aside className="panel">
        <h1>Roadworks impact preview</h1>
        {demoData && <p className="demo">Demo network. Run the data scripts to load real Melbourne streets.</p>}
        {warming && <p className="demo">Warming the network model&hellip; first results in a few seconds.</p>}

        <nav className="plans" aria-label="Plans">
          {scenarios.map((s, i) => (
            <button key={s.name} type="button" className={i === active && !comparing ? "plate on" : "plate"}
              onClick={() => { setActive(i); setComparing(false); }}>
              Plan {s.name}
            </button>
          ))}
          {scenarios.length === 1
            ? <button type="button" className="ghost" onClick={addPlanB}>Copy as plan B</button>
            : <button type="button" className={comparing ? "ghost on" : "ghost"} onClick={() => setComparing((c) => !c)}>Compare</button>}
        </nav>

        <ScenarioForm key={current.name} scenario={current} onChange={update} />
      </aside>

      <main className="stage">
        <MapView
          center={center}
          scenario={current}
          results={results[active]}
          onPick={pick}
          onZoneChange={(offset_m, length_m) =>
            // One number, two inputs: the drag writes the same work_length_m the form slider edits,
            // so the map and the parameter panel can never show different lengths.
            update({ closure_offset_m: Math.max(offset_m, 0), work_length_m: Math.round(length_m) })
          }
        />
        <div className="below-map">
          {comparing && scenarios.length === 2
            ? <CompareView scenarios={scenarios} results={results.slice(0, 2)} />
            : (
              <>
                <ResultsPanel results={results[active]} />
                <CommsPanel scenario={current} results={results[active]} />
              </>
            )}
        </div>
      </main>
    </div>
  );
}
