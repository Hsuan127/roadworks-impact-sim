import { useState } from "react";
import { post } from "../api";
import type { ScenarioResults } from "../hooks/useScenarioResults";
import type { Comms, ScenarioParams } from "../types";
import NoticeText from "./NoticeText";

export default function CommsPanel({ scenario, results }: { scenario: ScenarioParams; results: ScenarioResults }) {
  const [comms, setComms] = useState<Comms | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function draft() {
    setBusy(true);
    setError(null);
    try {
      setComms(await post<Comms>("/api/comms", {
        scenario, network: results.network.data, transit: results.transit.data, equipment: results.equipment.data,
      }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="comms">
      <header>
        <h2>Messages</h2>
        <button type="button" onClick={draft} disabled={busy || !results.network.data}>
          {busy ? "Drafting…" : comms ? "Redraft messages" : "Draft VMS and notice"}
        </button>
      </header>
      {error && <p className="error">{error}</p>}
      {comms && (
        <>
          <div className="vms-row">
            {comms.vms_messages.map((m, i) => (
              <div key={i} className="vms" aria-label={`VMS message ${i + 1}: ${m.join(" ")}`}>
                {m.map((line, j) => <span key={j}>{line}</span>)}
              </div>
            ))}
          </div>
          <NoticeText markdown={comms.public_notice_md} />
          <p className="fine">{comms.disclaimer} Written by {comms.generated_by === "llm" ? "AI from computed facts" : "template"}.</p>
        </>
      )}
    </section>
  );
}
