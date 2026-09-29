import type { EquipmentLayout, EquipmentResult, NetworkImpact, ScenarioParams, TransitImpact } from "../types";
import { toModuleRequests } from "../segments";
import { useModuleResult } from "./useModuleResult";

/** Builds each module's request from ONLY the fields that module depends on. */
export function useScenarioResults(s: ScenarioParams | null) {
  const body = s ? toModuleRequests(s) : { network: null, transit: null, equipment: null, layout: null };
  return {
    network: useModuleResult<NetworkImpact>("/api/impact/network", body.network),
    transit: useModuleResult<TransitImpact>("/api/impact/transit", body.transit),
    equipment: useModuleResult<EquipmentResult>("/api/equipment", body.equipment),
    layout: useModuleResult<EquipmentLayout>("/api/equipment/layout", body.layout),
  };
}

export type ScenarioResults = ReturnType<typeof useScenarioResults>;

/** Simple comparable index for A/B suggestions. TODO(P2): agree the weighting with the team. */
export function impactIndex(r: ScenarioResults): number | null {
  const n = r.network.data;
  if (!n) return null;
  return n.affected_trips_pct * 100 * n.avg_extra_min + 5 * n.sensitive_facilities.length;
}
