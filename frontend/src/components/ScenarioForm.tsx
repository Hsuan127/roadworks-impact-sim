import { useState } from "react";
import { post } from "../api";
import { colorFor } from "../identity";
import { autoName, envelope, lastDay, newSegment, segmentLabel, timing } from "../segments";
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

const dayLabel = (d: string) => new Date(`${d}T00:00`).toLocaleDateString("en-AU", { day: "numeric", month: "short" });

/** Who drew the segment, on a shared plan. */
function Owner({ name }: { name: string | null | undefined }) {
  if (!name) return null;
  return <span className="owner" title={`Drawn by ${name}`}><i style={{ background: colorFor(name) }} />{name}</span>;
}

function StatusTag({ full }: { full: boolean | undefined }) {
  if (full === undefined) return null;
  return <span className={full ? "tag closure" : "tag zone"}>{full ? "Road closure" : "Work zone"}</span>;
}

/** Why the network model treats this segment as a road closure or a work zone. The status is derived,
 *  not chosen: it says whether any lane is left open, which is what the traffic numbers assume. */
function statusReason(g: Segment, full: boolean | undefined): string | null {
  if (full === undefined) return null;
  const where = g.direction === "both" ? "in either direction" : g.direction;
  const lanes = `${g.lanes_closed} lane${g.lanes_closed > 1 ? "s" : ""}`;
  if (g.targets.includes("full")) return "Road closure: the whole carriageway is closed to vehicles.";
  if (full) return `Road closure: closing ${lanes} leaves no lane open ${where} on this street.`;
  if (g.targets.includes("traffic_lane"))
    return g.direction === "both"
      ? `Work zone: ${lanes} closed each way, traffic still passes on at least one side.`
      : `Work zone: ${lanes} closed ${where}, traffic still passes.`;
  return "Work zone: no traffic lane is closed, so vehicles are not affected.";
}

export default function ScenarioForm({
  scenario: s, onChange, pathError, status, activeSeg, onSelectSegment, onNewSegment, onChangeSegment, onDeleteSegment, onUndoPoint,
}: Props) {
  const [text, setText] = useState("");
  const [parseMsg, setParseMsg] = useState<string | null>(null);
  const active = s.segments.find((g) => g.id === activeSeg) ?? null;
  const span = envelope(s);
  const mixed = new Set(s.segments.map((g) => timing(g, s).time_window)).size > 1;
  const when = (g: Segment) => {
    const x = timing(g, s);
    return `${dayLabel(x.start_date)}–${dayLabel(lastDay(x))} · ${WINDOWS.find((w) => w.value === x.time_window)!.label.split(" ")[0]}`;
  };

  async function prefill() {
    setParseMsg("Reading description…");
    try {
      const r = await post<ParseResult>("/api/parse", { text });
      // Named fields only: location and speed come from the map, never from the description.
      const { targets, direction, lanes_closed, start_date, duration_days, time_window, work_type } = r.fields;
      const plan = {
        ...(start_date && { start_date }), ...(duration_days && { duration_days }), ...(work_type && { work_type }),
        ...(time_window && { time_window, custom_hours: time_window === "custom" ? timing(active, s).custom_hours ?? [10, 14] : null }),
      };
      // When belongs to a segment too: the one being edited, or every segment when none is selected.
      if (!active && Object.keys(plan).length > 0) onChange({ segments: s.segments.map((g) => ({ ...g, ...plan })) });
      // What is closed belongs to a segment: apply it to the one being edited.
      const seg = { ...(targets?.length && { targets }), ...(direction && { direction }), ...(lanes_closed && { lanes_closed }) };
      const skipped = active || Object.keys(seg).length === 0 ? [] : Object.keys(seg);
      if (active) onChangeSegment(active.id, { ...plan, ...seg });
      const filled = Object.keys(plan).length > 0 || (active !== null && Object.keys(seg).length > 0);
      setParseMsg([
        filled ? "Filled. Check each field below." : "Nothing was filled.",
        skipped.length > 0 && `Not applied (select a segment first): ${skipped.join(", ").replace(/_/g, " ")}.`,
        r.missing.length > 0 && `Still needed: ${r.missing.join(", ").replace(/_/g, " ")}.`,
      ].filter(Boolean).join(" "));
    } catch (e) {
      setParseMsg((e as Error).message);
    }
  }

  function segmentEditor(g: Segment) {
    const points = g.waypoints.length;
    const t = timing(g, s);
    const set = (patch: Partial<Segment>) => onChangeSegment(g.id, patch);
    const toggleTarget = (t: ClosureTarget) =>
      set({ targets: g.targets.includes(t) ? g.targets.filter((x) => x !== t) : [...g.targets, t] });
    return (
      <div key={g.id} className="segment on">
        <div className="segment-head">
          <input className="seg-name" aria-label="Segment name" value={g.name ?? ""} placeholder={autoName(g)}
            onChange={(e) => set({ name: e.target.value || null })} />
          <StatusTag full={status?.[g.id]} />
        </div>
        <Owner name={g.owner} />
        {statusReason(g, status?.[g.id]) && <p className="status-reason">{statusReason(g, status?.[g.id])}</p>}
        <p className="hint">
          {points === 0 && "Click a street. "}
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
            <input type="number" min={1} max={4} value={g.lanes_closed} onChange={(e) => set({ lanes_closed: Math.min(4, Math.max(1, Number(e.target.value) || 1)) })} />
          </label>
        </div>
        <label>Speed limit (km/h)
          <input type="number" min={10} max={110} step={10} value={g.speed_limit_kmh ?? ""} placeholder="From map data"
            onChange={(e) => set({ speed_limit_kmh: e.target.value ? Number(e.target.value) : null })} />
        </label>

        <div className="seg-when">
          <div className="row">
            <label>Start date
              <input type="date" value={t.start_date} onChange={(e) => e.target.value && set({ start_date: e.target.value })} />
            </label>
            <label>Duration (days)
              <input type="number" min={1} max={365} value={t.duration_days}
                onChange={(e) => set({ duration_days: Math.min(365, Math.max(1, Number(e.target.value) || 1)) })} />
            </label>
          </div>
          <div className="chips" role="radiogroup" aria-label="Daily hours">
            {WINDOWS.map((w) => (
              <label key={w.value} className={t.time_window === w.value ? "chip on" : "chip"}>
                <input type="radio" name={`window-${s.name}-${g.id}`} checked={t.time_window === w.value}
                  onChange={() => set({ time_window: w.value, custom_hours: w.value === "custom" ? t.custom_hours ?? [10, 14] : null })} />
                {w.label}
              </label>
            ))}
          </div>
          {t.time_window === "custom" && t.custom_hours && (
            <div className="row">
              <label>From <input type="number" min={0} max={23} value={t.custom_hours[0]} onChange={(e) => set({ custom_hours: [Number(e.target.value), t.custom_hours![1]] })} /></label>
              <label>To <input type="number" min={1} max={24} value={t.custom_hours[1]} onChange={(e) => set({ custom_hours: [t.custom_hours![0], Number(e.target.value)] })} /></label>
            </div>
          )}
          <label>Work type
            <select value={t.work_type} onChange={(e) => set({ work_type: e.target.value as ScenarioParams["work_type"] })}>
              <option value="excavation">Excavation</option>
              <option value="non_excavation">No excavation</option>
            </select>
          </label>
        </div>
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
        {s.segments.map((g) => (g.id === activeSeg
          ? segmentEditor(g)
          : (
            <button key={g.id} type="button" className="segment" onClick={() => onSelectSegment(g.id)}>
              <span>
                {segmentLabel(g)}{!g.road_name && " · not drawn"}{g.length_m > 0 && ` · ${Math.round(g.length_m)} m`}
                <span className="seg-when-short">{when(g)}{g.owner && <> · <Owner name={g.owner} /></>}</span>
              </span>
              <StatusTag full={status?.[g.id]} />
            </button>
          )))}
        {activeSeg === null
          ? <p className="hint">Click the map where segment {newSegment(s).id} starts.</p>
          : <button type="button" className="add-segment" onClick={onNewSegment}>+ New segment</button>}
        {pathError && <p className="error">{pathError}</p>}
      </fieldset>

      {span && (
        <p className="plan-span">
          <strong>Whole plan:</strong> {dayLabel(span.start_date)}–{dayLabel(lastDay(span))} ({span.duration_days} day{span.duration_days > 1 ? "s" : ""})
          {mixed && <> · segments run different hours: equipment follows each segment, messages describe night works</>}
        </p>
      )}
    </form>
  );
}
