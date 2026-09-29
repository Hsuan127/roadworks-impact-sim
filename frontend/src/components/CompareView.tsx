import { impactIndex, type ScenarioResults } from "../hooks/useScenarioResults";
import { drawnSegments } from "../segments";
import type { ScenarioParams } from "../types";

const FIELDS: { key: string; label: string; get: (s: ScenarioParams) => string }[] = [
  { key: "segments", label: "Segments", get: (s) => String(drawnSegments(s).length) },
  { key: "closed", label: "Closed", get: (s) => [...new Set(drawnSegments(s).flatMap((g) => g.targets))].map((x) => x.replace("_", " ")).join(", ") },
  { key: "direction", label: "Direction", get: (s) => [...new Set(drawnSegments(s).map((g) => g.direction))].join(", ") },
  { key: "lanes", label: "Lanes", get: (s) => drawnSegments(s).map((g) => g.lanes_closed).join(" / ") },
  { key: "time_window", label: "Hours", get: (s) => s.time_window },
  { key: "duration_days", label: "Days", get: (s) => String(s.duration_days) },
  { key: "length", label: "Length (m)", get: (s) => String(Math.round(drawnSegments(s).reduce((sum, g) => sum + g.length_m, 0))) },
];

export default function CompareView({ scenarios, results }: { scenarios: ScenarioParams[]; results: ScenarioResults[] }) {
  const idx = results.map(impactIndex);
  const ready = idx.every((v) => v !== null);
  const best = ready ? idx.indexOf(Math.min(...(idx as number[]))) : -1;

  return (
    <section className="compare">
      <table>
        <thead>
          <tr><th />{scenarios.map((s, i) => <th key={s.name} className={i === best ? "best" : ""}>Plan {s.name}</th>)}</tr>
        </thead>
        <tbody>
          {FIELDS.map((f) => {
            const vals = scenarios.map(f.get);
            const differs = new Set(vals).size > 1;
            return (
              <tr key={f.key} className={differs ? "differs" : ""}>
                <th>{f.label}</th>{vals.map((v, i) => <td key={i}>{v}</td>)}
              </tr>
            );
          })}
          <tr><th>Trips affected</th>{results.map((r, i) => <td key={i}>{r.network.data ? `${Math.round(r.network.data.affected_trips_pct * 100)}%` : "…"}</td>)}</tr>
          <tr><th>Average delay</th>{results.map((r, i) => <td key={i}>{r.network.data ? `${r.network.data.avg_extra_min.toFixed(1)} min` : "…"}</td>)}</tr>
          <tr><th>Facility alerts</th>{results.map((r, i) => <td key={i}>{r.network.data?.sensitive_facilities.length ?? "…"}</td>)}</tr>
          <tr><th>Hire cost</th>{results.map((r, i) => <td key={i}>{r.equipment.data ? `$${Math.round(r.equipment.data.total_cost_aud)}` : "…"}</td>)}</tr>
        </tbody>
      </table>
      {best >= 0 && <p className="verdict">Plan {scenarios[best].name} has the lower impact index. Highlighted rows are what differs.</p>}
    </section>
  );
}
