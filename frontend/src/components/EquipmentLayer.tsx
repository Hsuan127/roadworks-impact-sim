import { divIcon, latLngBounds, type DivIcon } from "leaflet";
import { useState } from "react";
import { Marker, Tooltip, useMap, useMapEvents } from "react-leaflet";
import type { EquipmentLayout, Placement, Segment } from "../types";

/** Individual items only make sense once a few metres are visible; below this zoom each segment gets one badge. */
const DETAIL_ZOOM = 18;

const SIGN_CODE: Record<string, string> = {
  sign_roadwork_ahead: "RW", sign_lane_status: "LS", sign_road_closed: "RC", sign_detour_ahead: "DA", sign_detour: "DT",
  sign_end_roadwork: "END", sign_bike_lane_closed_ahead: "BKA", sign_bike_lane_closed: "BK", sign_bicycle_ahead: "BA",
  sign_footpath_closed: "FP", sign_use_other_footpath: "UOF", sign_pedestrians_arrow: "PED",
};
const KIND: Record<string, string> = {
  cone: "cone", barrier_water_filled: "barrier", barrier_end_treatment: "barrier", barrier_board: "fence", ped_fence: "fence",
  vms_board: "vms", arrow_board: "arrow", light_tower: "light",
};
const LABEL: Record<string, string> = { vms: "VMS", arrow: "➜", light: "✦" };

const icons = new Map<string, DivIcon>();
function iconFor(p: Placement): DivIcon {
  const kind = KIND[p.item_id] ?? "sign";
  const text = kind === "sign" ? SIGN_CODE[p.item_id] ?? "S" : LABEL[kind] ?? "";
  const key = `${kind}|${text}|${p.in_stock}`;
  if (!icons.has(key)) {
    const size: [number, number] = kind === "cone" || kind === "barrier" || kind === "fence" ? [10, 10] : [26, 18];
    icons.set(key, divIcon({ className: `eq eq-${kind}${p.in_stock ? "" : " eq-short"}`, html: text, iconSize: size }));
  }
  return icons.get(key)!;
}

// No iconSize: the badge sizes itself to its text (centred by CSS on the inner span).
const badge = (html: string) => divIcon({ className: "eq-badge", html, iconSize: undefined });

export default function EquipmentLayer({ layout, segments }: { layout: EquipmentLayout; segments: Segment[] }) {
  const map = useMap();
  const [zoom, setZoom] = useState(map.getZoom());
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) });

  if (zoom >= DETAIL_ZOOM) {
    return (
      <>
        {layout.placements.map((p, i) => (
          <Marker key={i} position={[p.lat, p.lng]} icon={iconFor(p)} interactive keyboard={false}>
            <Tooltip>
              <strong>{p.name}</strong>{!p.in_stock && " · not enough in the depot"}<br />{p.reason}
            </Tooltip>
          </Marker>
        ))}
      </>
    );
  }

  // Zoomed out: one badge per segment; clicking it zooms to that segment's layout.
  return (
    <>
      {segments.map((g) => {
        const items = layout.placements.filter((p) => p.segment_id === g.id);
        if (items.length === 0 || g.geometry.length < 2) return null;
        const short = items.some((p) => !p.in_stock);
        const mid = g.geometry[Math.floor(g.geometry.length / 2)];
        return (
          <Marker key={g.id} position={mid}
            icon={badge(`<span class="${short ? "eq-badge-short" : ""}">Segment ${segments.indexOf(g) + 1}: ${items.length} items${short ? " · shortage" : ""}</span>`)}
            eventHandlers={{ click: () => map.fitBounds(latLngBounds(items.map((p) => [p.lat, p.lng])), { padding: [40, 40], maxZoom: 19 }) }}>
            <Tooltip direction="top">Click to zoom in and see where each item goes</Tooltip>
          </Marker>
        );
      })}
    </>
  );
}
