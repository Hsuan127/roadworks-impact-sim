import { useEffect, useRef, useState } from "react";
import { get, put } from "../api";
import type { Person, ScenarioParams, SharedPlan } from "../types";

const POLL_MS = 2000;
const QUIET_MS = 1500; // don't pull someone else's version while this person is mid-edit

/**
 * Keeps the local plans and the server copy in step: push local edits (debounced), pull newer
 * versions by polling. Last write wins; a remote version only lands when this person has been
 * quiet for a moment, so it never yanks a field out from under their cursor.
 */
export function useSharedPlan(
  id: string | null, scenarios: ScenarioParams[], setScenarios: (s: ScenarioParams[]) => void, me: Person,
) {
  const [viewers, setViewers] = useState<Person[]>([]);
  const [lastBy, setLastBy] = useState<Person | null>(null);
  const version = useRef(0);
  const fromServer = useRef<string | null>(null); // the scenarios exactly as last received: not a local edit
  const lastEdit = useRef(0);

  const take = (p: SharedPlan) => {
    version.current = p.version;
    setViewers(p.viewers);
    setLastBy(p.updated_by);
  };

  useEffect(() => {
    if (!id || scenarios.length === 0) return;
    const json = JSON.stringify(scenarios);
    if (json === fromServer.current) return;
    lastEdit.current = Date.now();
    const t = setTimeout(() => {
      put<SharedPlan>(`/api/plans/${id}`, { scenarios, author: me }).then(take).catch(() => undefined);
    }, 500);
    return () => clearTimeout(t);
  }, [id, scenarios, me]);

  useEffect(() => {
    if (!id) return;
    const t = setInterval(() => {
      get<SharedPlan>(`/api/plans/${id}?who=${encodeURIComponent(me.name)}&color=${encodeURIComponent(me.color)}`)
        .then((p) => {
          setViewers(p.viewers);
          if (p.version > version.current && Date.now() - lastEdit.current > QUIET_MS) {
            take(p);
            fromServer.current = JSON.stringify(p.scenarios);
            setScenarios(p.scenarios);
          }
        })
        .catch(() => undefined);
    }, POLL_MS);
    return () => clearInterval(t);
  }, [id, me, setScenarios]);

  /** Record the version this copy started from, so the first poll does not reapply it. */
  const adopt = (p: SharedPlan) => {
    take(p);
    fromServer.current = JSON.stringify(p.scenarios);
  };
  return { viewers, lastBy, adopt };
}
