import type { ScenarioResults } from "../hooks/useScenarioResults";
import Freshness from "./Freshness";
import type { Facility } from "../types";

const pct = (x: number) => `${Math.round(x * 100)}%`;
const names = (fs: Facility[]) => fs.map((f) => f.name).join(", ");
const aud = (n: number) => n.toLocaleString("en-AU", { style: "currency", currency: "AUD", maximumFractionDigits: 0 });

export default function ResultsPanel({ results }: { results: ScenarioResults }) {
  const { network, transit, equipment } = results;
  const n = network.data, t = transit.data, e = equipment.data;
  const atWorks = n?.sensitive_facilities.filter((f) => f.near === "works") ?? [];
  const onDetour = n?.sensitive_facilities.filter((f) => f.near !== "works") ?? [];

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
            {n.affected_trips_pct > 0 && (
              <p className="hint">
                {pct(n.rerouted_trips_pct)} of trips take a detour, {pct(n.slowed_trips_pct)} keep their route but drive slower through the work zone.
              </p>
            )}
            {atWorks.length > 0 && (
              <p className="alert">Works are next to {names(atWorks)}. Check access and emergency routes.</p>
            )}
            {onDetour.length > 0 && (
              <p className="alert">Detour traffic passes {names(onDetour)}. Check emergency access.</p>
            )}
            {n.load_increase.length > 0 && (
              <p className="hint">Busier streets: {[...new Set(n.load_increase.slice(0, 5).map((l) => l.road_name ?? "unnamed"))].join(", ")}</p>
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
