import { useEffect, useRef, useState } from "react";
import { post } from "../api";

/**
 * Fetches one module's result, keyed ONLY by that module's inputs.
 * Changing a field a module doesn't use leaves its key (and result) untouched,
 * so e.g. editing the duration never re-runs the network model.
 */
const cache = new Map<string, unknown>();

export interface ModuleState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  updatedAt: number | null; // when this module last produced a NEW result
}

export function useModuleResult<T>(url: string, body: unknown | null, debounceMs = 250): ModuleState<T> {
  const key = body === null ? null : url + JSON.stringify(body);
  const [state, setState] = useState<ModuleState<T>>({ data: null, loading: false, error: null, updatedAt: null });
  const latest = useRef<string | null>(null);

  useEffect(() => {
    latest.current = key;
    if (key === null) return;
    if (cache.has(key)) {
      setState((s) => ({ data: cache.get(key) as T, loading: false, error: null, updatedAt: s.data === cache.get(key) ? s.updatedAt : Date.now() }));
      return;
    }
    setState((s) => ({ ...s, loading: true, error: null }));
    const t = setTimeout(() => {
      post<T>(url, body)
        .then((data) => {
          cache.set(key, data);
          if (latest.current === key) setState({ data, loading: false, error: null, updatedAt: Date.now() });
        })
        .catch((e: Error) => {
          if (latest.current === key) setState((s) => ({ ...s, loading: false, error: e.message }));
        });
    }, debounceMs);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
