import { Fragment, useEffect, useState } from "react";
import { get, patch } from "../api";
import type { HireQuery, QueryStatus } from "../types";

const aud = (n: number) => `$${Math.round(n).toLocaleString()}`;
const day = (d: string) => new Date(`${d}T00:00`).toLocaleDateString("en-AU", { day: "numeric", month: "short" });
const WINDOW = { day: "Day", night: "Night", custom: "Custom hours" } as const;
const STATUS: Record<QueryStatus, string> = { new: "New", accepted: "Accepted", declined: "Declined", countered: "Counter-offer sent" };

/** RPM Hire's side (?view=depot): every query, with the stock it needs once overlapping jobs are counted. */
export default function DepotInbox() {
  const [queries, setQueries] = useState<HireQuery[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  const load = () => get<HireQuery[]>("/api/queries").then(setQueries).catch((e) => setError((e as Error).message));
  useEffect(() => {
    load();
    const t = setInterval(load, 3000); // new queries appear without a reload
    return () => clearInterval(t);
  }, []);

  async function decide(id: string, status: QueryStatus) {
    await patch<HireQuery>(`/api/queries/${id}`, { status });
    load();
  }

  const open = queries?.filter((q) => q.status !== "declined") ?? [];
  const pipeline = open.reduce((sum, q) => sum + q.total_cost_aud, 0);
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><span /></span>
          <div>
            <h1>RPM Hire · Query inbox</h1>
            <p className="tagline">Every plan contractors have sent, with the stock it needs on those days</p>
          </div>
        </div>
        <nav className="plans"><a className="ghost" href="/">Planner view</a></nav>
      </header>
      <main className="depot">
        {error && <p className="error">{error}</p>}
        {queries && (
          <p className="depot-summary">
            <span><strong>{queries.filter((q) => q.status === "new").length}</strong> awaiting a decision</span>
            <span><strong>{aud(pipeline)}</strong> estimated hire across open queries</span>
            <span><strong>{open.filter((q) => q.stock_gaps.length > 0).length}</strong> short on stock if all go ahead</span>
          </p>
        )}
        {queries?.length === 0 && <p className="hint">No queries yet. Send one from the planner view.</p>}
        {queries && queries.length > 0 && (
          <div className="table-scroll">
            <table className="equip depot-table">
              <thead>
                <tr><th>Query</th><th>Contractor</th><th>Where</th><th>When</th><th className="num">Est. hire</th><th>Stock</th><th>Status</th></tr>
              </thead>
              <tbody>
                {queries.map((q) => (
                  <Fragment key={q.id}>
                    <tr className={q.status === "declined" ? "muted" : ""} onClick={() => setOpenId(openId === q.id ? null : q.id)}>
                      <td><strong>{q.id}</strong></td>
                      <td>{q.contact.company}<br /><span className="hint">{q.contact.contact}</span></td>
                      <td>{q.segments.join(", ")}{q.road_classes.length > 0 && <><br /><span className="hint">{q.road_classes.join(", ")}</span></>}</td>
                      <td>{day(q.start_date)}–{day(q.end_date)}<br /><span className="hint">{WINDOW[q.time_window]}</span></td>
                      <td className="num">{aud(q.total_cost_aud)}</td>
                      <td>
                        {q.stock_gaps.length === 0
                          ? <span className="tag zone">Covered</span>
                          : <span className="tag closure">{q.stock_gaps.length} item{q.stock_gaps.length > 1 ? "s" : ""} short</span>}
                        {q.overlaps_with.length > 0 && <><br /><span className="hint">Same days as {q.overlaps_with.join(", ")}</span></>}
                      </td>
                      <td>{STATUS[q.status]}</td>
                    </tr>
                    {openId === q.id && (
                      <tr className="depot-detail">
                        <td colSpan={7}>
                          {q.contact.note && <p><strong>Note:</strong> {q.contact.note}</p>}
                          {q.stock_gaps.length > 0 && (
                            <ul className="depot-gaps">
                              {q.stock_gaps.map((g) => (
                                <li key={g.item_id}>
                                  <strong>{g.name}</strong>: this job needs {g.requested}{g.overlapping_demand > g.requested && <>, {g.overlapping_demand} with the queries on the same days</>}; in stock {g.stock}
                                </li>
                              ))}
                            </ul>
                          )}
                          <p className="hint">{q.items.length} equipment lines. Sent {new Date(q.submitted_at).toLocaleString("en-AU")}.</p>
                          <div className="path-actions">
                            <button type="button" className="query-btn" onClick={() => decide(q.id, "accepted")}>Accept</button>
                            <button type="button" onClick={() => decide(q.id, "countered")}>Counter-offer</button>
                            <button type="button" onClick={() => decide(q.id, "declined")}>Decline</button>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="fine">Hire figures come from the rule-based equipment list and simulated stock; they are estimates to decide on, not quotes.</p>
      </main>
    </div>
  );
}
