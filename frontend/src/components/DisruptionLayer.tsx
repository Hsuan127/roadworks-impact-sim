import { Polyline, Tooltip } from "react-leaflet";
import { OTHER_WORKS } from "../colors";
import { LEVEL_LABEL, permitDates, permitHours } from "../disruptions";
import type { Disruption } from "../types";

/** Other permitted works, darker = more of our hours shared and closer. Each line is sent to the back
 *  when added, so our closure and detours, drawn in the same pane, stay on top. */
export default function DisruptionLayer({ disruptions }: { disruptions: Disruption[] }) {
  // Most relevant first: each is sent to the back in turn, so the dark lines end up over the pale ones.
  const ordered = [...disruptions].sort((a, b) => b.relevance - a.relevance);
  return (
    <>
      {ordered.flatMap((d) => d.lines.map((line, i) => (
        <Polyline key={`${d.id}-${i}`} positions={line} pathOptions={{ ...OTHER_WORKS[d.level], lineCap: "butt" }}
          eventHandlers={{ add: (e) => e.target.bringToBack() }}>
          <Tooltip sticky>
            <strong>{d.road_name ?? "Unnamed street"}</strong>{d.cross_street && <> near {d.cross_street}</>}
            <br />{LEVEL_LABEL[d.level]} &middot; {d.distance_m.toLocaleString()} m from the works
            <br />{d.cause ?? "Planned works"}{d.impact_type && <> &middot; {d.impact_type}</>}{d.direction && <> &middot; {d.direction}</>}
            <br />Permitted {permitDates(d)}, {permitHours(d)}
            {d.level > 0 && <><br />{Math.round(d.overlap * 100)}% of your working hours fall in its permitted hours</>}
          </Tooltip>
        </Polyline>
      )))}
    </>
  );
}
