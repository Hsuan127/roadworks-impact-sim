import type { ScenarioResults } from "../hooks/useScenarioResults";
import Freshness from "./Freshness";

const aud = (n: number) => n.toLocaleString("en-AU", { style: "currency", currency: "AUD", maximumFractionDigits: 0 });

export default function ResultsPanel({ results }: { results: ScenarioResults }) {
  const { network, transit, equipment } = results;
  const n = network.data, t = transit.data, e = equipment.data;

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
            {n.closed_aadt && (
              <p className="hint">
                This road carries <strong>{n.closed_aadt.aadt.toLocaleString()}</strong> vehicles a day
                {n.closed_aadt.heavy ? <> ({n.closed_aadt.heavy.toLocaleString()} heavy)</> : null}
                {" "}&mdash; VicRoads {n.closed_aadt.year}
                {n.closed_aadt.method === "Actual" ? ", measured" : ", estimated"}.
              </p>
            )}
            {n.unreachable_trips_pct > 0 && (
              <p className="alert">
                {Math.round(n.unreachable_trips_pct * 100)}% of modelled trips have no route at all
                inside the study area after this closure.
              </p>
            )}
            {n.sensitive_facilities.length > 0 && (
              <p className="alert">Detour traffic passes {n.sensitive_facilities.map((f) => f.name).join(", ")}. Check emergency access.</p>
            )}
            {n.load_increase.length > 0 && (
              <p className="hint">Busier streets: {[...new Set(n.load_increase.slice(0, 5).map((l) => l.road_name ?? "unnamed"))].join(", ")}</p>
            )}
            {n.ped_detour_m !== null && n.ped_detour_basis === "street_centreline" && (
              <p className="fine">
                Walking detour measured on road centrelines, not footpaths &mdash; treat it as an
                over-estimate.
              </p>
            )}
            <p className="fine">{n.note}</p>
          </>
        )}
      </section>

      <section>
        <header><h2>Public transport</h2><Freshness {...transit} /></header>
        {transit.error && <p className="error">{transit.error}</p>}
        {t && (t.routes.length === 0
          ? <p className="hint">No routes run through the closed section.</p>
          : <ul className="routes">{t.routes.map((r) => (
              <li key={r.route_id} className={r.mode}>
                <strong>{r.short_name}</strong> {r.mode}{r.needs_replacement && <span className="alert-inline"> needs replacement buses</span>}
              </li>))}
            </ul>)}
        {t && t.stops.length > 0 && <p className="hint">{t.stops.length} stops within 400 m</p>}
      </section>

      <section>
        <header><h2>Equipment</h2><Freshness {...equipment} /></header>
        {equipment.error && <p className="error">{equipment.error}</p>}
        {e && (
          <>
            {e.shortages.length > 0 && <p className="alert">Not enough in the depot: {e.shortages.join(", ")}</p>}
            <table className="equip">
              <thead><tr><th>Item</th><th>Qty</th><th>Why</th><th className="num">Hire</th></tr></thead>
              <tbody>
                {e.items.map((i, k) => (
                  <tr key={k} className={i.in_stock ? "" : "short"}>
                    <td>{i.name}</td><td className="num">{i.qty}</td><td className="why">{i.reason}</td><td className="num">{aud(i.cost_aud)}</td>
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
