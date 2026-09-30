import { addDays, daysBetween, type DayView, envelope, lastDay, segmentLabel, timing, worksOn } from "../segments";
import type { ScenarioParams, TimeWindow } from "../types";

const WINDOW_LABEL: Record<TimeWindow, string> = { day: "Day", night: "Night", custom: "Custom hours" };
const dayLabel = (d: string, weekday = false) =>
  new Date(`${d}T00:00`).toLocaleDateString("en-AU", { ...(weekday && { weekday: "short" }), day: "numeric", month: "short" });

interface Props {
  scenario: ScenarioParams;
  view: DayView | null;
  onView: (v: DayView | null) => void;
  activeSeg: string | null;
  onSelectSegment: (id: string) => void;
}

/** Each segment's works as a bar over the plan's days, and a day picker that sets what the map and the
 *  traffic numbers show: only the segments on site that day, in those hours. */
export default function Timeline({ scenario: s, view, onView, activeSeg, onSelectSegment }: Props) {
  const span = envelope(s);
  if (!span || s.segments.length === 0) return null;
  const days = span.duration_days;
  const pct = (d: string) => (daysBetween(span.start_date, d) / days) * 100;
  const day = view && view.day >= span.start_date && view.day <= lastDay(span) ? view.day : null;

  const today = day ? s.segments.filter((g) => worksOn(g, s, day)) : [];
  const windows = [...new Set(today.map((g) => timing(g, s).time_window))];
  const window = day && windows.length > 1 ? view?.window ?? windows[0] : null;
  const shown = window ? today.filter((g) => timing(g, s).time_window === window) : today;
  const pick = (d: string, w: TimeWindow | null = null) => {
    const ws = [...new Set(s.segments.filter((g) => worksOn(g, s, d)).map((g) => timing(g, s).time_window))];
    onView({ day: d, window: ws.length > 1 ? (w && ws.includes(w) ? w : ws[0]) : null });
  };

  return (
    <section className="timeline" aria-label="Schedule">
      <header>
        <h2>Schedule</h2>
        <div className="timeline-mode">
          <button type="button" className={day ? "chip" : "chip on"} onClick={() => onView(null)}>Whole plan</button>
          <button type="button" className={day ? "chip on" : "chip"} onClick={() => pick(day ?? span.start_date)}>One day</button>
        </div>
      </header>

      <div className="gantt">
        {s.segments.map((g) => {
          const t = timing(g, s);
          const on = !day || shown.includes(g);
          return (
            <button key={g.id} type="button" className={`gantt-row${g.id === activeSeg ? " active" : ""}${on ? "" : " off"}`}
              onClick={() => onSelectSegment(g.id)}>
              <span className="gantt-label">{segmentLabel(g)}</span>
              <span className="gantt-track">
                <span className={`gantt-bar w-${t.time_window}`}
                  style={{ left: `${pct(t.start_date)}%`, width: `${(t.duration_days / days) * 100}%` }}
                  title={`${dayLabel(t.start_date)}–${dayLabel(lastDay(t))}, ${WINDOW_LABEL[t.time_window]}`} />
                {day && <span className="gantt-now" style={{ left: `${pct(day) + 50 / days}%` }} />}
              </span>
            </button>
          );
        })}
        <div className="gantt-axis">
          <span />
          <span>{dayLabel(span.start_date)}</span>
          <span>{dayLabel(lastDay(span))}</span>
        </div>
      </div>

      {day && (
        <div className="timeline-day">
          <label>
            <span>Showing <strong>{dayLabel(day, true)}</strong></span>
            <input type="range" min={0} max={days - 1} value={daysBetween(span.start_date, day)}
              onChange={(e) => pick(addDays(span.start_date, Number(e.target.value)), window)} />
          </label>
          {windows.length > 1 && (
            <div className="chips" role="radiogroup" aria-label="Hours shown">
              {windows.map((w) => (
                <button key={w} type="button" className={w === window ? "chip on" : "chip"} onClick={() => pick(day, w)}>
                  {WINDOW_LABEL[w]}
                </button>
              ))}
            </div>
          )}
          <p className="hint">
            {shown.length === 0
              ? "No works on site this day: nothing to model."
              : `${shown.length} of ${s.segments.length} segment${s.segments.length > 1 ? "s" : ""} on site${window ? ` in ${WINDOW_LABEL[window].toLowerCase()} hours` : ""}. Traffic and public transport show this day only; equipment and messages cover the whole plan.`}
          </p>
        </div>
      )}
    </section>
  );
}
