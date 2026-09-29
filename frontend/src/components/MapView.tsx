import { CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMapEvents } from "react-leaflet";
import { COLORS } from "../colors";
import { projectOntoPolyline } from "../geometry";
import type { ScenarioResults } from "../hooks/useScenarioResults";
import type { LatLng, ScenarioParams } from "../types";

function ClickToPick({ onPick }: { onPick: (lat: number, lng: number) => void }) {
  useMapEvents({ click: (e) => onPick(e.latlng.lat, e.latlng.lng) });
  return null;
}

interface Props {
  center: [number, number];
  scenario: ScenarioParams | null;
  results: ScenarioResults;
  onPick: (lat: number, lng: number) => void;
  /** Drag handles move the work zone along the road; both values feed the same fields the form edits. */
  onZoneChange?: (offsetM: number, lengthM: number) => void;
}

export default function MapView({ center, scenario, results, onPick, onZoneChange }: Props) {
  const net = results.network.data;
  const transit = results.transit.data;
  const zone = net?.work_zone_geometry ?? [];
  const corridor = net?.corridor_geometry ?? [];

  // Handles are only meaningful once the server has told us where the corridor runs.
  const canDrag = Boolean(onZoneChange && zone.length >= 2 && corridor.length >= 2 && net);
  const offset = scenario?.closure_offset_m ?? 0;
  const length = scenario?.work_length_m ?? 0;
  const start = net?.corridor_start_m ?? 0;

  /** Turn a dragged position into metres along the corridor, then into offset/length. */
  const moveHandle = (which: "start" | "end") => (latlng: { lat: number; lng: number }) => {
    if (!onZoneChange || !net) return;
    const along = start + projectOntoPolyline([latlng.lat, latlng.lng] as LatLng, corridor);
    if (which === "start") {
      const end = offset + length;
      const next = Math.min(along, end - net.closure_quantum_m);
      onZoneChange(next, end - next);
    } else {
      onZoneChange(offset, Math.max(along - offset, net.closure_quantum_m));
    }
  };
  return (
    <MapContainer center={center} zoom={15} className="map" scrollWheelZoom>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <ClickToPick onPick={onPick} />

      {net?.load_increase.map((l, i) => (
        <Polyline key={i} positions={l.geometry} pathOptions={{ color: COLORS.detour, weight: 3 + 8 * l.delta, opacity: 0.35 + 0.6 * l.delta }}>
          <Tooltip sticky>{l.road_name ?? "Unnamed street"}: {Math.round(l.delta * 100)}% of rerouted trips</Tooltip>
        </Polyline>
      ))}

      {/* Two different truths, drawn differently on purpose. The faint band is every edge the model
          actually closed (routing can only remove whole OSM edges); the solid bar is the physical
          work zone you would set out on site. */}
      {net && net.closed_geometry.length > 0 && (
        <Polyline positions={net.closed_geometry} pathOptions={{ color: COLORS.works, weight: 12, opacity: 0.2, lineCap: "butt" }}>
          <Tooltip sticky>Modelled as closed: {net.closed_edges.length} road segment{net.closed_edges.length === 1 ? "" : "s"}</Tooltip>
        </Polyline>
      )}
      {net && zone.length > 0 && (
        <Polyline positions={zone} pathOptions={{ color: COLORS.works, weight: 9, lineCap: "butt" }}>
          <Tooltip sticky>Work zone {Math.round(length)} m{canDrag ? " · drag either end" : ""}</Tooltip>
        </Polyline>
      )}

      {canDrag && (
        <>
          <Marker draggable position={zone[0]} eventHandlers={{ dragend: (e) => moveHandle("start")(e.target.getLatLng()) }}>
            <Tooltip direction="top">Work zone start</Tooltip>
          </Marker>
          <Marker draggable position={zone[zone.length - 1]} eventHandlers={{ dragend: (e) => moveHandle("end")(e.target.getLatLng()) }}>
            <Tooltip direction="top">Work zone end</Tooltip>
          </Marker>
        </>
      )}

      {transit?.stops.map((s) => (
        <CircleMarker key={s.stop_id} center={[s.lat, s.lng]} radius={5} pathOptions={{ color: COLORS.tram, fillOpacity: 0.9 }}>
          <Tooltip>{s.name} · {s.distance_m} m</Tooltip>
        </CircleMarker>
      ))}

      {net?.sensitive_facilities.map((f, i) => (
        <CircleMarker key={i} center={[f.lat, f.lng]} radius={9} pathOptions={{ color: COLORS.alert, weight: 3, fillOpacity: 0.25 }}>
          <Tooltip permanent direction="top">{f.name}</Tooltip>
        </CircleMarker>
      ))}

      {scenario && <CircleMarker center={[scenario.location.lat, scenario.location.lng]} radius={4} pathOptions={{ color: COLORS.asphalt, fillOpacity: 1 }} />}
    </MapContainer>
  );
}
