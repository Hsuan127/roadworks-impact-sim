import { useState } from "react";
import { post } from "../api";
import type { ClosureTarget, ParseResult, ScenarioParams, TimeWindow } from "../types";

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
}

export default function ScenarioForm({ scenario: s, onChange }: Props) {
  const [text, setText] = useState("");
  const [parseMsg, setParseMsg] = useState<string | null>(null);

  const toggleTarget = (t: ClosureTarget) =>
    onChange({ targets: s.targets.includes(t) ? s.targets.filter((x) => x !== t) : [...s.targets, t] });

  async function prefill() {
    setParseMsg("Reading description…");
    try {
      const r = await post<ParseResult>("/api/parse", { text });
      const { road_name: _ignored, ...fields } = r.fields;
      onChange(fields);
      setParseMsg(r.missing.length ? `Filled. Still needed: ${r.missing.join(", ")}` : "Filled. Check each field below.");
    } catch (e) {
      setParseMsg((e as Error).message);
    }
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
        <legend>Location</legend>
        <p className="location">{s.location.road_name ?? "Click a street on the map"}</p>
        <p className="hint">Click the map to move the works.</p>
      </fieldset>

      <fieldset>
        <legend>What is closed</legend>
        <div className="chips">
          {TARGETS.map((t) => (
            <label key={t.value} className={s.targets.includes(t.value) ? "chip on" : "chip"}>
              <input type="checkbox" checked={s.targets.includes(t.value)} onChange={() => toggleTarget(t.value)} />
              {t.label}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="row">
        <label>Direction
          <select value={s.direction} onChange={(e) => onChange({ direction: e.target.value as ScenarioParams["direction"] })}>
            <option value="citybound">Citybound</option>
            <option value="outbound">Outbound</option>
            <option value="both">Both</option>
          </select>
        </label>
        <label>Lanes closed
          <input type="number" min={1} max={4} value={s.lanes_closed} onChange={(e) => onChange({ lanes_closed: Number(e.target.value) })} />
        </label>
      </div>

      <label>Work zone length <output>{s.work_length_m} m</output>
        <input type="range" min={5} max={300} step={5} value={s.work_length_m} onChange={(e) => onChange({ work_length_m: Number(e.target.value) })} />
      </label>

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
        <label>Speed limit (km/h)
          <input type="number" min={10} max={110} step={10} value={s.speed_limit_kmh ?? ""} placeholder="From map data"
            onChange={(e) => onChange({ speed_limit_kmh: e.target.value ? Number(e.target.value) : null })} />
        </label>
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
