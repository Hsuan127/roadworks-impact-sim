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
  const [warming, setWarming] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pathError, setPathError] = useState<string | null>(null);
  const [activeSeg, setActiveSeg] = useState<string | null>(null); // null: the next map click starts a new segment

  useEffect(() => {
    Promise.all([
      get<{ lat: number; lng: number }>("/api/map-center"),
      get<ScenarioParams>("/api/demo-scenario"),
      get<{ demo_graph: boolean; baseline_ready: boolean }>("/api/health"),
    ])
      .then(([c, s, h]) => {
        setCenter([c.lat, c.lng]);
        setScenarios([s]);
        setActiveSeg(s.segments[0]?.id ?? null);
        setDemoData(h.demo_graph);
        setWarming(!h.baseline_ready);
      })
      .catch(() => setLoadError("Can't reach the API on port 8000. Start it with: uvicorn app.main:app --reload"));
  }, []);

  // The routing baseline takes several seconds to build on the real graph and is warmed at startup.
  // Poll until it lands so a cold start reads as "warming", not as a hang.
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

  const updateSegment = (id: string, patch: Partial<Segment>) =>
    setScenarios((all) => all.map((s, i) => (i === active
      ? { ...s, segments: s.segments.map((g) => (g.id === id ? { ...g, ...patch } : g)) }
      : s)));

  // Clicks can arrive faster than /api/path answers: build each edit on the newest requested points,
  // and apply only the newest answer. Tracked per plan AND segment: a copied plan reuses segment ids.
  const pending = useRef<Record<string, LatLng[]>>({});
  const seq = useRef<Record<string, number>>({});
  const planKey = (id: string) => `${current!.name}/${id}`;
  // Segments whose speed limit the user typed: redrawing the line must not replace it with the map's value.
  const typedSpeed = useRef(new Set<string>());
  const points = (id: string) => pending.current[planKey(id)] ?? current!.segments.find((g) => g.id === id)?.waypoints ?? [];

  async function setWaypoints(id: string, next: LatLng[]) {
    setPathError(null);
    const plan = current!.name; // the answer goes to this plan, even if the user has switched since
    const key = planKey(id);
    const apply = (patch: Partial<Segment>) => setScenarios((all) => all.map((s) => (s.name === plan
      ? { ...s, segments: s.segments.map((g) => (g.id === id ? { ...g, ...patch } : g)) }
      : s)));
    const mine = (seq.current[key] = (seq.current[key] ?? 0) + 1);
    const done = () => { if (mine === seq.current[key]) delete pending.current[key]; };
    pending.current[key] = next;
    if (next.length === 0) {
      done();
      apply({ waypoints: [], edges: [], geometry: [], length_m: 0, road_name: null, road_class: null });
      return;
    }
    try {
      const p = await post<PathResult>("/api/path", { points: next });
      if (mine !== seq.current[key]) return;
      apply({
        waypoints: p.waypoints, edges: p.edges, geometry: p.geometry, length_m: p.length_m,
        road_name: p.road_name, road_class: p.road_class,
        ...(p.speed_limit_kmh !== null && !typedSpeed.current.has(key) && { speed_limit_kmh: p.speed_limit_kmh }),
      });
    } catch (e) {
      if (mine === seq.current[key]) setPathError((e as Error).message);
    } finally {
      done();
    }
  }

  function changeSegment(id: string, patch: Partial<Segment>) {
    if ("speed_limit_kmh" in patch) {
      // Cleared: back to the map's value on the next redraw.
      if (patch.speed_limit_kmh === null) typedSpeed.current.delete(planKey(id));
      else typedSpeed.current.add(planKey(id));
    }
    updateSegment(id, patch);
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
    const key = planKey(id);
    seq.current[key] = (seq.current[key] ?? 0) + 1; // drop any answer still on its way
    delete pending.current[key];
    typedSpeed.current.delete(key);
    update({ segments: current!.segments.filter((g) => g.id !== id) });
    if (activeSeg === id) setActiveSeg(null);
  }

  function addPlanB() {
    const a = scenarios[0].name;
    for (const k of [...typedSpeed.current]) if (k.startsWith(`${a}/`)) typedSpeed.current.add(`B/${k.slice(a.length + 1)}`);
    setScenarios((all) => [all[0], { ...all[0], name: "B" }]);
    setActive(1);
  }

  if (loadError) return <main className="empty"><p>{loadError}</p></main>;
  if (!center || !current) return <main className="empty"><p>Loading the network…</p></main>;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><span /></span>
          <div>
            <h1>Roadworks Impact Preview</h1>
            <p className="tagline">See the knock-on effects before anything goes on site</p>
          </div>
        </div>
        <nav className="plans" aria-label="Plans">
          {scenarios.map((s, i) => (
            <button key={s.name} type="button"
              className={i === active ? (comparing ? "plate viewing" : "plate on") : "plate"}
              aria-current={i === active && !comparing ? "page" : undefined}
              onClick={() => { setActive(i); setComparing(false); setActiveSeg(s.segments[s.segments.length - 1]?.id ?? null); }}>
              Plan {s.name}
            </button>
          ))}
          {scenarios.length === 1
            ? <button type="button" className="ghost" onClick={addPlanB}>+ Copy as plan B</button>
            : <button type="button" className={comparing ? "ghost on" : "ghost"} onClick={() => setComparing((c) => !c)}>Compare plans</button>}
        </nav>
      </header>
      {demoData && <p className="demo">Demo network. Run the data scripts to load real Melbourne streets.</p>}
      {warming && <p className="demo">Warming the network model&hellip; first results in a few seconds.</p>}

      <div className="layout">
        <aside className="panel" aria-label="Closure settings">
          <ScenarioForm key={current.name} scenario={current} onChange={update} pathError={pathError}
            status={results[active].network.data?.full_closure}
            activeSeg={activeSeg} onSelectSegment={setActiveSeg} onNewSegment={() => setActiveSeg(null)}
            onChangeSegment={changeSegment} onDeleteSegment={deleteSegment}
            onUndoPoint={(id) => setWaypoints(id, points(id).slice(0, -1))} />
        </aside>

        <main className="stage">
          <MapView center={center} scenario={current} results={results[active]} activeSeg={activeSeg}
            planLabel={scenarios.length > 1 ? `Plan ${current.name}` : undefined}
            onPick={pick} onSelectSegment={setActiveSeg}
            onRemovePoint={(id, i) => setWaypoints(id, points(id).filter((_, j) => j !== i))}
            onMovePoint={(id, i, lat, lng) => setWaypoints(id, points(id).map((p, j) => (j === i ? [lat, lng] : p)))} />
          {comparing && scenarios.length === 2
            ? <CompareView scenarios={scenarios} results={results.slice(0, 2)} shown={current.name} />
            : (
              <>
                <ResultsPanel results={results[active]} />
                <CommsPanel scenario={current} results={results[active]} />
              </>
            )}
        </main>
      </div>

      <footer className="footer">
        <p><strong>Draft planning aid.</strong> Every output needs sign-off by a qualified traffic management practitioner.</p>
        {/* Credit only what this machine actually loaded: without the data files the app runs on demo data. */}
        <p>
          {demoData ? "Demo street network" : <>Streets &copy; OpenStreetMap contributors &middot; Traffic volumes: VicRoads AADT</>}
          {results[active].transit.data && !results[active].transit.data.is_demo_data && <> &middot; Public transport: PTV GTFS</>}
          {" "}&middot; FEIT Hackathon 2026
        </p>
      </footer>
    </div>
  );
}
