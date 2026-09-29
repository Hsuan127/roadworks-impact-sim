import { useState } from "react";
import { post } from "../api";
import type { ClosureTarget, ParseResult, ScenarioParams, Segment, TimeWindow } from "../types";

const TARGETS: { value: ClosureTarget; label: string }[] = [
  { value: "traffic_lane", label: "Traffic lane" },
  { value: "bike_lane", label: "Bike lane" },
  { value: "footpath", label: "Footpath" },
  { value: "full", label: "Whole carriageway" },
];

const WINDOWS: { value: TimeWindow; label: string }[] = [
  { value: "day", label: "Day (9:30–15:30)" },
  { value: "night", label: "Night (20:00–05:00)" },
  { value: "custom", label: "Custom hours" },
];

interface Props {
  scenario: ScenarioParams;
  onChange: (patch: Partial<ScenarioParams>) => void;
  pathError: string | null;
  status: Record<string, boolean> | undefined; // segment id → full road closure?
  activeSeg: string | null;
  onSelectSegment: (id: string) => void;
  onNewSegment: () => void;
  onChangeSegment: (id: string, patch: Partial<Segment>) => void;
  onDeleteSegment: (id: string) => void;
  onUndoPoint: (id: string) => void;
}

function StatusTag({ full }: { full: boolean | undefined }) {
  if (full === undefined) return null;
  return <span className={full ? "tag closure" : "tag zone"}>{full ? "Road closure" : "Work zone"}</span>;
}

export default function ScenarioForm({
  scenario: s, onChange, pathError, status, activeSeg, onSelectSegment, onNewSegment, onChangeSegment, onDeleteSegment, onUndoPoint,
}: Props) {
  const [text, setText] = useState("");
  const [parseMsg, setParseMsg] = useState<string | null>(null);
  const active = s.segments.find((g) => g.id === activeSeg) ?? null;

  async function prefill() {
    setParseMsg("Reading description…");
    try {
      const r = await post<ParseResult>("/api/parse", { text });
      const { road_name: _ignored, targets, direction, lanes_closed, ...plan } = r.fields;
      onChange(plan);
      // What is closed belongs to a segment: apply it to the one being edited.
      if (active) {
        onChangeSegment(active.id, {
          ...(targets && { targets }), ...(direction && { direction }), ...(lanes_closed && { lanes_closed }),
        });
      }
      setParseMsg(r.missing.length ? `Filled. Still needed: ${r.missing.join(", ")}` : "Filled. Check each field below.");
    } catch (e) {
      setParseMsg((e as Error).message);
    }
  }

  function segmentEditor(g: Segment, n: number) {
    const points = g.waypoints.length;
    const set = (patch: Partial<Segment>) => onChangeSegment(g.id, patch);
    const toggleTarget = (t: ClosureTarget) =>
      set({ targets: g.targets.includes(t) ? g.targets.filter((x) => x !== t) : [...g.targets, t] });
    return (
      <div key={g.id} className="segment on">
        <div className="segment-head">
          <p className="location">Segment {n} · {g.road_name ?? (points === 0 ? "click a street" : "click where it ends")}</p>
          <StatusTag full={status?.[g.id]} />
        </div>
        <p className="hint">
          {points < 2
            ? "Click where the works start, then where they end, in the direction of traffic."
            : `${Math.round(g.length_m)} m drawn. Click to extend, click a point to remove it, drag a point to move it.`}
        </p>
        <div className="path-actions">
          {points > 0 && <button type="button" onClick={() => onUndoPoint(g.id)}>Undo last point</button>}
          <button type="button" onClick={() => onDeleteSegment(g.id)}>Delete segment</button>
        </div>

        <div className="chips" role="group" aria-label="What is closed">
          {TARGETS.map((t) => (
            <label key={t.value} className={g.targets.includes(t.value) ? "chip on" : "chip"}>
              <input type="checkbox" checked={g.targets.includes(t.value)} onChange={() => toggleTarget(t.value)} />
              {t.label}
            </label>
          ))}
        </div>

        <div className="row">
          <label>Direction
            <select value={g.direction} onChange={(e) => set({ direction: e.target.value as Segment["direction"] })}>
              <option value="citybound">Citybound</option>
              <option value="outbound">Outbound</option>
              <option value="both">Both</option>
            </select>
          </label>
          <label>Lanes closed
            <input type="number" min={1} max={4} value={g.lanes_closed} onChange={(e) => set({ lanes_closed: Number(e.target.value) })} />
          </label>
        </div>
        <label>Speed limit (km/h)
          <input type="number" min={10} max={110} step={10} value={g.speed_limit_kmh ?? ""} placeholder="From map data"
            onChange={(e) => set({ speed_limit_kmh: e.target.value ? Number(e.target.value) : null })} />
        </label>
      </div>
    );
  }

  return (
    <form className="form" onSubmit={(e) => e.preventDefault()}>
      <details className="prefill">
        <summary>Describe the works in one sentence</summary>
        <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Next Tuesday for three days, dig up the citybound kerb lane and bike lane on Flemington Rd near Racecourse Rd, about 30 m." />
        <button type="button" onClick={prefill} disabled={!text.trim()}>Fill the form</button>
        {parseMsg && <p className="hint">{parseMsg}</p>}
      </details>

      <fieldset>
        <legend>Closed segments</legend>
        {s.segments.map((g, i) => (g.id === activeSeg
          ? segmentEditor(g, i + 1)
          : (
            <button key={g.id} type="button" className="segment" onClick={() => onSelectSegment(g.id)}>
              <span>Segment {i + 1} · {g.road_name ?? "not drawn"}{g.length_m > 0 && ` · ${Math.round(g.length_m)} m`}</span>
              <StatusTag full={status?.[g.id]} />
            </button>
          )))}
        {activeSeg === null
          ? <p className="hint">Click the map where segment {s.segments.length + 1} starts.</p>
          : <button type="button" className="add-segment" onClick={onNewSegment}>+ New segment</button>}
        {pathError && <p className="error">{pathError}</p>}
      </fieldset>

      <div className="row">
        <label>Start date
          <input type="date" value={s.start_date} onChange={(e) => onChange({ start_date: e.target.value })} />
        </label>
        <label>Duration (days)
          <input type="number" min={1} max={365} value={s.duration_days} onChange={(e) => onChange({ duration_days: Number(e.target.value) })} />
        </label>
      </div>

      <fieldset>
        <legend>Daily hours</legend>
        <div className="chips">
          {WINDOWS.map((w) => (
            <label key={w.value} className={s.time_window === w.value ? "chip on" : "chip"}>
              <input type="radio" name={`window-${s.name}`} checked={s.time_window === w.value}
                onChange={() => onChange({ time_window: w.value, custom_hours: w.value === "custom" ? s.custom_hours ?? [10, 14] : null })} />
              {w.label}
            </label>
          ))}
        </div>
        {s.time_window === "custom" && s.custom_hours && (
          <div className="row">
            <label>From <input type="number" min={0} max={23} value={s.custom_hours[0]} onChange={(e) => onChange({ custom_hours: [Number(e.target.value), s.custom_hours![1]] })} /></label>
            <label>To <input type="number" min={1} max={24} value={s.custom_hours[1]} onChange={(e) => onChange({ custom_hours: [s.custom_hours![0], Number(e.target.value)] })} /></label>
          </div>
        )}
      </fieldset>

      <div className="row">
        <label>Work type
          <select value={s.work_type} onChange={(e) => onChange({ work_type: e.target.value as ScenarioParams["work_type"] })}>
            <option value="excavation">Excavation</option>
            <option value="non_excavation">No excavation</option>
          </select>
        </label>
      </div>
    </form>
  );
}
