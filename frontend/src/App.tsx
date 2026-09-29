import { useEffect, useRef, useState } from "react";
import { get, post } from "./api";
import CommsPanel from "./components/CommsPanel";
import CompareView from "./components/CompareView";
import MapView from "./components/MapView";
import ResultsPanel from "./components/ResultsPanel";
import ScenarioForm from "./components/ScenarioForm";
import { useScenarioResults } from "./hooks/useScenarioResults";
import { newSegment } from "./segments";
import type { LatLng, PathResult, ScenarioParams, Segment } from "./types";

export default function App() {
  const [center, setCenter] = useState<[number, number] | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioParams[]>([]);
  const [active, setActive] = useState(0);
  const [comparing, setComparing] = useState(false);
  const [demoData, setDemoData] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pathError, setPathError] = useState<string | null>(null);
  const [activeSeg, setActiveSeg] = useState<string | null>(null); // null: the next map click starts a new segment

  useEffect(() => {
    Promise.all([
      get<{ lat: number; lng: number }>("/api/map-center"),
      get<ScenarioParams>("/api/demo-scenario"),
      get<{ demo_graph: boolean }>("/api/health"),
    ])
      .then(([c, s, h]) => {
        setCenter([c.lat, c.lng]);
        setScenarios([s]);
        setActiveSeg(s.segments[0]?.id ?? null);
        setDemoData(h.demo_graph);
      })
      .catch(() => setLoadError("Can't reach the API on port 8000. Start it with: uvicorn app.main:app --reload"));
  }, []);

  // Hooks are always called for two slots; slot B is idle until a second plan exists.
  const resultsA = useScenarioResults(scenarios[0] ?? null);
  const resultsB = useScenarioResults(scenarios[1] ?? null);
  const results = [resultsA, resultsB];
  const current = scenarios[active] ?? null;

  const update = (patch: Partial<ScenarioParams>) =>
    setScenarios((all) => all.map((s, i) => (i === active ? { ...s, ...patch } : s)));

  const updateSegment = (id: string, patch: Partial<Segment>) =>
    setScenarios((all) => all.map((s, i) => (i === active
      ? { ...s, segments: s.segments.map((g) => (g.id === id ? { ...g, ...patch } : g)) }
      : s)));

  // Clicks can arrive faster than /api/path answers: build each edit on the newest requested points,
  // and apply only the newest answer (tracked per segment).
  const pending = useRef<Record<string, LatLng[]>>({});
  const seq = useRef<Record<string, number>>({});
  const points = (id: string) => pending.current[id] ?? current!.segments.find((g) => g.id === id)?.waypoints ?? [];

  async function setWaypoints(id: string, next: LatLng[]) {
    setPathError(null);
    const mine = (seq.current[id] = (seq.current[id] ?? 0) + 1);
    const done = () => { if (mine === seq.current[id]) delete pending.current[id]; };
    pending.current[id] = next;
    if (next.length === 0) {
      done();
      updateSegment(id, { waypoints: [], edges: [], geometry: [], length_m: 0, road_name: null, road_class: null });
      return;
    }
    try {
      const p = await post<PathResult>("/api/path", { points: next });
      if (mine !== seq.current[id]) return;
      updateSegment(id, {
        waypoints: p.waypoints, edges: p.edges, geometry: p.geometry, length_m: p.length_m,
        road_name: p.road_name, road_class: p.road_class,
        ...(p.speed_limit_kmh !== null && { speed_limit_kmh: p.speed_limit_kmh }),
      });
    } catch (e) {
      if (mine === seq.current[id]) setPathError((e as Error).message);
    } finally {
      done();
    }
  }

  function pick(lat: number, lng: number) {
    if (activeSeg && current!.segments.some((g) => g.id === activeSeg)) {
      setWaypoints(activeSeg, [...points(activeSeg), [lat, lng]]);
      return;
    }
    const seg = newSegment(current!);
    update({ segments: [...current!.segments, seg] });
    setActiveSeg(seg.id);
    setWaypoints(seg.id, [[lat, lng]]);
  }

  function deleteSegment(id: string) {
    seq.current[id] = (seq.current[id] ?? 0) + 1; // drop any answer still on its way
    delete pending.current[id];
    update({ segments: current!.segments.filter((g) => g.id !== id) });
    if (activeSeg === id) setActiveSeg(null);
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

        <nav className="plans" aria-label="Plans">
          {scenarios.map((s, i) => (
            <button key={s.name} type="button" className={i === active && !comparing ? "plate on" : "plate"}
              onClick={() => { setActive(i); setComparing(false); setActiveSeg(s.segments[s.segments.length - 1]?.id ?? null); }}>
              Plan {s.name}
            </button>
          ))}
          {scenarios.length === 1
            ? <button type="button" className="ghost" onClick={addPlanB}>Copy as plan B</button>
            : <button type="button" className={comparing ? "ghost on" : "ghost"} onClick={() => setComparing((c) => !c)}>Compare</button>}
        </nav>

        <ScenarioForm key={current.name} scenario={current} onChange={update} pathError={pathError}
          status={results[active].network.data?.full_closure}
          activeSeg={activeSeg} onSelectSegment={setActiveSeg} onNewSegment={() => setActiveSeg(null)}
          onChangeSegment={updateSegment} onDeleteSegment={deleteSegment}
          onUndoPoint={(id) => setWaypoints(id, points(id).slice(0, -1))} />
      </aside>

      <main className="stage">
        <MapView center={center} scenario={current} results={results[active]} activeSeg={activeSeg}
          onPick={pick} onSelectSegment={setActiveSeg}
          onRemovePoint={(id, i) => setWaypoints(id, points(id).filter((_, j) => j !== i))}
          onMovePoint={(id, i, lat, lng) => setWaypoints(id, points(id).map((p, j) => (j === i ? [lat, lng] : p)))} />
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
