import { DomEvent, divIcon } from "leaflet";
import { useState } from "react";
import { CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMapEvents } from "react-leaflet";
import { COLORS } from "../colors";
import type { ScenarioResults } from "../hooks/useScenarioResults";
import DisruptionLayer from "./DisruptionLayer";
import EquipmentLayer from "./EquipmentLayer";
import { segmentLabel } from "../segments";
import type { ScenarioParams } from "../types";

const POINT_ICON = divIcon({ className: "waypoint", iconSize: [14, 14] });

function ClickToPick({ onPick }: { onPick: (lat: number, lng: number) => void }) {
  useMapEvents({ click: (e) => onPick(e.latlng.lat, e.latlng.lng) });
  return null;
}

interface Props {
  center: [number, number];
  scenario: ScenarioParams | null;
  results: ScenarioResults;
  activeSeg: string | null;
  onPick: (lat: number, lng: number) => void;
  onSelectSegment: (id: string) => void;
  onRemovePoint: (segment: string, index: number) => void;
  onMovePoint: (segment: string, index: number, lat: number, lng: number) => void;
  planLabel?: string; // which plan the map shows, once there is more than one
}

export default function MapView({ center, scenario, results, activeSeg, onPick, onSelectSegment, onRemovePoint, onMovePoint, planLabel }: Props) {
  const net = results.network.data;
  const transit = results.transit.data;
  const equip = results.equipment.data;
  const layout = results.layout.data;
  const others = results.disruptions.data;
  const [showOthers, setShowOthers] = useState(true);
  const active = scenario?.segments.find((g) => g.id === activeSeg) ?? null;
  // While a segment is being started, clicks on other lines add points (e.g. A-C starting on A-B's end);
  // otherwise a click on a line selects that segment.
  const drawing = !active || active.waypoints.length < 2;
  return (
    <div className="map-wrap">
    <MapContainer center={center} zoom={15} className="map" scrollWheelZoom maxZoom={19}>
      {/* Standard OSM tiles, muted in styles.css, so the closure, detours and stops are the loudest things on screen. */}
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
      />
      <ClickToPick onPick={onPick} />
      {showOthers && others?.available && <DisruptionLayer disruptions={others.disruptions} />}

      {net?.load_increase.map((l, i) => (
        <Polyline key={i} positions={l.geometry} pathOptions={{ color: COLORS.detour, weight: 3 + 8 * l.delta, opacity: 0.35 + 0.6 * l.delta }}>
          <Tooltip sticky>{l.road_name ?? "Unnamed street"}: {Math.round(l.delta * 100)}% of rerouted trips</Tooltip>
        </Polyline>
      ))}

      {/* Each segment as drawn. Colour waits for the network result: orange = road closure, dashed amber = work zone. */}
      {scenario?.segments.filter((g) => g.geometry.length > 1).map((g) => {
        const full = net?.full_closure[g.id];
        const traffic = net?.segment_traffic[g.id];
        const weight = g.id === activeSeg ? 11 : 8;
        return (
          <Polyline
            key={`${g.id}-${String(full)}`}
            positions={g.geometry}
            pathOptions={full === undefined
              ? { color: COLORS.asphalt, weight, lineCap: "butt", opacity: 0.5 }
              : full
                ? { color: COLORS.works, weight, lineCap: "butt" }
                : { color: COLORS.workZone, weight, lineCap: "butt", dashArray: "12 8" }}
            eventHandlers={{
              click: (e) => {
                if (drawing || g.id === activeSeg) return; // let the click reach the map and add a point
                DomEvent.stopPropagation(e);
                onSelectSegment(g.id);
              },
            }}
          >
            <Tooltip sticky>
              {segmentLabel(g)}
              {full !== undefined && (full ? " · Road closure: no vehicles can pass" : " · Work zone: traffic still passes")}
              {full === false && traffic && (
                <>
                  <br />
                  {Math.round(traffic.through_trips_pct * 100)}% of trips still drive through
                  {traffic.slowdown_factor !== null && traffic.slowdown_factor > 1 && `, travel time ×${traffic.slowdown_factor}`}
                </>
              )}
            </Tooltip>
          </Polyline>
        );
      })}

      {transit?.stops.map((s) => (
        <CircleMarker key={s.stop_id} center={[s.lat, s.lng]} radius={5} pathOptions={{ color: COLORS.tram, fillOpacity: 0.9 }}>
          <Tooltip>{s.name} · {s.distance_m} m</Tooltip>
        </CircleMarker>
      ))}

      {net?.sensitive_facilities.map((f, i) => (
        <CircleMarker key={i} center={[f.lat, f.lng]} radius={9} pathOptions={{ color: COLORS.alert, weight: 3, fillOpacity: 0.25 }}>
          {/* Only facilities at the works keep a label; detour ones on hover, or they bury the closure. */}
          <Tooltip permanent={f.near === "works"} direction="top">{f.name}{f.near === "works" ? " · next to works" : " · on detour"}</Tooltip>
        </CircleMarker>
      ))}

      {active?.waypoints.map((p, i) => (
        <Marker
          key={`${i}-${p[0]}-${p[1]}`}
          position={p}
          icon={POINT_ICON}
          draggable
          eventHandlers={{
            click: () => onRemovePoint(active.id, i),
            dragend: (e) => {
              const { lat, lng } = e.target.getLatLng();
              onMovePoint(active.id, i, lat, lng);
            },
          }}
        >
          <Tooltip>Point {i + 1} · click to remove, drag to move</Tooltip>
        </Marker>
      ))}
      {layout && scenario && <EquipmentLayer layout={layout} segments={scenario.segments} />}
    </MapContainer>

    {planLabel && <p className="map-plan" aria-live="polite">Showing {planLabel}</p>}
    <ul className="legend" aria-label="Map legend">
      <li><i aria-hidden="true" className="key-closure" />Road closure</li>
      <li><i aria-hidden="true" className="key-zone" />Work zone</li>
      <li><i aria-hidden="true" className="key-detour" />Busier street</li>
      <li><i aria-hidden="true" className="key-stop" />Tram / bus stop</li>
      <li><i aria-hidden="true" className="key-facility" />Hospital, school, emergency</li>
      {others?.available && (
        <li>
          <label className="key-toggle">
            <input type="checkbox" checked={showOthers} onChange={(e) => setShowOthers(e.target.checked)} />
            <i aria-hidden="true" className="key-others" />Other planned works: darker = same hours, closer
          </label>
        </li>
      )}
    </ul>

    {equip && (
      <aside className="map-card" aria-label="Equipment summary">
        <p><strong>Estimated hire</strong> ${Math.round(equip.total_cost_aud).toLocaleString()}</p>
        <p className="fine">An estimate, not a quote. Send a query to confirm with the depot.</p>
        {layout && <p className="fine">Zoom in on a segment to see where each item goes. Layout is schematic.</p>}
      </aside>
    )}
    </div>
  );
}
