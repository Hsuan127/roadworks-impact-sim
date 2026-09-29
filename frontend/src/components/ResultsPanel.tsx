import type { ScenarioResults } from "../hooks/useScenarioResults";
import Freshness from "./Freshness";
import type { Facility } from "../types";

const pct = (x: number) => `${Math.round(x * 100)}%`;
// Long facility lists bury the point: name three, count the rest (all are on the map).
const names = (fs: Facility[]) =>
  fs.length <= 3 ? fs.map((f) => f.name).join(", ") : `${fs.slice(0, 3).map((f) => f.name).join(", ")} and ${fs.length - 3} more`;
const aud = (n: number) => n.toLocaleString("en-AU", { style: "currency", currency: "AUD", maximumFractionDigits: 0 });

export default function ResultsPanel({ results }: { results: ScenarioResults }) {
  const { network, transit, equipment } = results;
  const n = network.data, t = transit.data, e = equipment.data;
  const atWorks = n?.sensitive_facilities.filter((f) => f.near === "works") ?? [];
  const onDetour = n?.sensitive_facilities.filter((f) => f.near === "detour") ?? [];

  return (
    <div className="results">
      <section>
        <header><h2>Traffic</h2><Freshness {...network} /></header>
        {network.error && <p className="error">{network.error}</p>}
        {n && (
          <>
            <dl className="metrics">
              <div><dt>Trips affected</dt><dd>{Math.round(n.affected_trips_pct * 100)}%</dd></div>
              <div><dt>Average delay</dt><dd>{n.avg_extra_min.toFixed(1)} min</dd></div>
              <div><dt>Worst delay</dt><dd>{n.max_extra_min.toFixed(1)} min</dd></div>
              {n.ped_detour_m !== null && <div><dt>Walking detour</dt><dd>{Math.round(n.ped_detour_m)} m</dd></div>}
            </dl>
            {n.unmodelled_segments.length > 0 && (
              <p className="alert">
                Not in these numbers: segment{n.unmodelled_segments.length > 1 && "s"} {n.unmodelled_segments.join(", ")},
                on a street cut off from the modelled network (one-way, dead end or ramp). Its effect on traffic was not calculated.
              </p>
            )}
            {n.affected_trips_pct > 0 && (
              <p className="hint">
                {pct(n.rerouted_trips_pct)} of trips take a detour, {pct(n.slowed_trips_pct)} keep their route but drive slower, through the work zone or on busier streets.
              </p>
            )}
            {n.unreachable_trips_pct > 0 && (
              <p className="alert">
                {pct(n.unreachable_trips_pct)} of modelled trips have no route at all inside the study area after this closure.
              </p>
            )}
            {Object.entries(n.closed_aadt).map(([id, a]) => (
              <p key={id} className="hint">
                {Object.keys(n.closed_aadt).length > 1 && <>Segment {id}: </>}
                this road carries <strong>{a.aadt.toLocaleString()}</strong> vehicles a day
                {a.heavy ? <> ({a.heavy.toLocaleString()} heavy)</> : null}
                {" "}&mdash; VicRoads {a.year}{a.method === "Actual" ? ", measured" : ", estimated"}.
              </p>
            ))}
            {atWorks.length > 0 && (
              <p className="alert">Works are next to {names(atWorks)}. Check access and emergency routes.</p>
            )}
            {onDetour.length > 0 && (
              <p className="alert">Detour traffic passes {names(onDetour)}. Check emergency access.</p>
            )}
            {n.load_increase.length > 0 && (
              <p className="hint">Busier streets: {[...new Set(n.load_increase.slice(0, 5).map((l) => l.road_name ?? "unnamed"))].join(", ")}</p>
            )}
            {n.ped_detour_basis === "street_centreline" && (
              <p className="fine">Walking detour measured on road centrelines, not footpaths &mdash; treat it as an over-estimate.</p>
            )}
            <p className="fine">{n.note}</p>
          </>
        )}
      </section>

      <section>
        <header><h2>Public transport</h2><Freshness {...transit} /></header>
        {transit.error && <p className="error">{transit.error}</p>}
        {t?.note && <p className="hint">{t.note}</p>}
        {t && !t.note && (t.routes.length === 0
          ? <p className="hint">No routes run through the closed section.</p>
          : <ul className="routes">{t.routes.map((r) => (
              <li key={r.route_id} className={r.mode}>
                <strong>{r.short_name}</strong> {r.mode}{r.needs_replacement && <span className="alert-inline"> needs replacement buses</span>}
              </li>))}
            </ul>)}
        {t && t.stops.length > 0 && (
          <>
            <p className="hint">{t.stops.length} stops within 400 m</p>
            <ul className="stops">{t.stops.map((s) => (
              <li key={s.stop_id}>
                {s.name}
                <span className="fine"> {Math.round(s.distance_m)} m{s.routes.length > 0 && ` · ${s.routes.join(", ")}`}</span>
              </li>))}
            </ul>
          </>)}
      </section>

      <section>
        <header><h2>Equipment</h2><Freshness {...equipment} /></header>
        {equipment.error && <p className="error">{equipment.error}</p>}
        {e && (
          <>
            {e.shortages.length > 0 && <p className="alert">Not enough in the depot: {e.shortages.join(", ")}</p>}
            {e.warnings.map((w, k) => <p key={k} className="alert">{w}</p>)}
            <table className="equip">
              <thead><tr><th>Item</th><th>Qty</th><th>Why</th><th className="num">Hire</th></tr></thead>
              <tbody>
                {e.items.map((i, k) => (
                  <tr key={k} className={i.in_stock ? "" : "short"}>
                    <td>{i.name}{i.supplier === "other" && <span className="hint"> (not hired from RPM)</span>}</td><td className="num">{i.qty}</td><td className="why">{i.reason}</td><td className="num">{aud(i.cost_aud)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot><tr><td colSpan={3}>Estimated hire</td><td className="num">{aud(e.total_cost_aud)}</td></tr></tfoot>
            </table>
            <p className="fine">{e.disclaimer}</p>
          </>
        )}
      </section>
    </div>
  );
}
