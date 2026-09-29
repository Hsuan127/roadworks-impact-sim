import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMapEvents } from "react-leaflet";
import { COLORS } from "../colors";
import type { ScenarioResults } from "../hooks/useScenarioResults";
import type { ScenarioParams } from "../types";

function ClickToPick({ onPick }: { onPick: (lat: number, lng: number) => void }) {
  useMapEvents({ click: (e) => onPick(e.latlng.lat, e.latlng.lng) });
  return null;
}

interface Props {
  center: [number, number];
  scenario: ScenarioParams | null;
  results: ScenarioResults;
  onPick: (lat: number, lng: number) => void;
}

export default function MapView({ center, scenario, results, onPick }: Props) {
  const net = results.network.data;
  const transit = results.transit.data;
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

      {net && <Polyline positions={net.closed_geometry} pathOptions={{ color: COLORS.works, weight: 9, lineCap: "butt" }} />}

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
