import type { EquipmentResult, NetworkImpact, ScenarioParams, TransitImpact } from "../types";
import { useModuleResult } from "./useModuleResult";

/** Builds each module's request from ONLY the fields that module depends on. */
export function useScenarioResults(s: ScenarioParams | null) {
  const edge = s?.location.edge ?? null;

  const networkBody = s && edge
    ? { edge, targets: [...s.targets].sort(), direction: s.direction, lanes_closed: s.lanes_closed, time_window: s.time_window }
    : null;

  const transitBody = s && edge ? { edge, targets: [...s.targets].sort() } : null;

  const equipmentBody = s
    ? {
        targets: [...s.targets].sort(), direction: s.direction, lanes_closed: s.lanes_closed,
        work_length_m: s.work_length_m, duration_days: s.duration_days, time_window: s.time_window,
        speed_limit_kmh: s.speed_limit_kmh, road_class: s.location.road_class, work_type: s.work_type,
      }
    : null;

  return {
    network: useModuleResult<NetworkImpact>("/api/impact/network", networkBody),
    transit: useModuleResult<TransitImpact>("/api/impact/transit", transitBody),
    equipment: useModuleResult<EquipmentResult>("/api/equipment", equipmentBody),
  };
}

export type ScenarioResults = ReturnType<typeof useScenarioResults>;

/** Simple comparable index for A/B suggestions. TODO(P2): agree the weighting with the team. */
export function impactIndex(r: ScenarioResults): number | null {
  const n = r.network.data;
  if (!n) return null;
  return n.affected_trips_pct * 100 * n.avg_extra_min + 5 * n.sensitive_facilities.length;
}
