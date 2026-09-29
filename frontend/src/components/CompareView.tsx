import { impactIndex, type ScenarioResults } from "../hooks/useScenarioResults";
import type { ScenarioParams } from "../types";

const FIELDS: { key: keyof ScenarioParams; label: string; fmt?: (v: unknown) => string }[] = [
  { key: "targets", label: "Closed", fmt: (v) => (v as string[]).map((x) => x.replace("_", " ")).join(", ") },
  { key: "direction", label: "Direction" },
  { key: "lanes_closed", label: "Lanes" },
  { key: "time_window", label: "Hours" },
  { key: "duration_days", label: "Days" },
  { key: "work_length_m", label: "Length (m)" },
];

export default function CompareView({ scenarios, results }: { scenarios: ScenarioParams[]; results: ScenarioResults[] }) {
  const idx = results.map(impactIndex);
  const ready = idx.every((v) => v !== null);
  const best = ready ? idx.indexOf(Math.min(...(idx as number[]))) : -1;
  const show = (s: ScenarioParams, f: (typeof FIELDS)[number]) => (f.fmt ? f.fmt(s[f.key]) : String(s[f.key]));

  return (
    <section className="compare">
      <table>
        <thead>
          <tr><th />{scenarios.map((s, i) => <th key={s.name} className={i === best ? "best" : ""}>Plan {s.name}</th>)}</tr>
        </thead>
        <tbody>
          {FIELDS.map((f) => {
            const vals = scenarios.map((s) => show(s, f));
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
