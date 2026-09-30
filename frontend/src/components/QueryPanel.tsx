import { useState } from "react";
import { post } from "../api";
import type { ScenarioResults } from "../hooks/useScenarioResults";
import { toModuleRequests } from "../segments";
import type { HireQuery, QueryContact, ScenarioParams } from "../types";

/** Bottom of the settings panel. The planner never sees stock: they send the plan out as a hire
 *  query, and the reply weighs it against other jobs on the same days. Who receives it is not fixed yet. */
export default function QueryPanel({ scenario, results }: { scenario: ScenarioParams; results: ScenarioResults }) {
  const [open, setOpen] = useState(false);
  const [contact, setContact] = useState<QueryContact>({ company: "", contact: "", email: null, note: "" });
  const [sent, setSent] = useState<HireQuery | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const equipment = toModuleRequests(scenario).equipment;
  const ready = equipment !== null && results.equipment.data !== null;

  async function send() {
    setBusy(true);
    setError(null);
    try {
      setSent(await post<HireQuery>("/api/queries", { scenario, equipment, contact }));
      setOpen(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const set = (patch: Partial<QueryContact>) => setContact((c) => ({ ...c, ...patch }));
  return (
    <section className="query" aria-label="Send a hire query">
      {sent && !open && (
        <p className="query-sent">
          Query <strong>{sent.id}</strong> sent for plan {scenario.name}. The reply will confirm equipment and price.
        </p>
      )}
      {!open ? (
        <button type="button" className="query-btn" disabled={!ready} onClick={() => setOpen(true)}>
          {sent ? "Send another query" : "Send hire query"}
        </button>
      ) : (
        <form className="query-form" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <p className="hint">
            The query carries this plan with its equipment list and dates; the reply gives availability and a quote.
          </p>
          <label>Company <input required value={contact.company} onChange={(e) => set({ company: e.target.value })} /></label>
          <label>Contact name <input required value={contact.contact} onChange={(e) => set({ contact: e.target.value })} /></label>
          <label>Email <input type="email" value={contact.email ?? ""} onChange={(e) => set({ email: e.target.value || null })} /></label>
          <label>Note <textarea rows={2} value={contact.note} onChange={(e) => set({ note: e.target.value })}
            placeholder="Flexible on dates? Need delivery before 7am?" /></label>
          {error && <p className="error">{error}</p>}
          <div className="path-actions">
            <button type="submit" className="query-btn" disabled={busy}>{busy ? "Sending…" : "Send query"}</button>
            <button type="button" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </form>
      )}
      {!ready && <p className="hint">Draw a segment first: the query carries its equipment list.</p>}
    </section>
  );
}
