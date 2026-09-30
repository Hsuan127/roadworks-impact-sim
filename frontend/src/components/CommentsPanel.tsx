import { useEffect, useState } from "react";
import { get, patch, post } from "../api";
import { segmentLabel } from "../segments";
import type { Comment, Person, ScenarioParams } from "../types";
import { Avatar } from "./People";

interface Props {
  planId: string | null;
  scenario: ScenarioParams;
  me: Person;
  activeSeg: string | null;
  onSelectSegment: (id: string) => void;
  onShare: () => Promise<string>;
}

const ago = (iso: string) => {
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : new Date(iso).toLocaleString("en-AU");
};

/** Feedback without redrawing: a supervisor or partner comments on the plan or on one segment, and
 *  the person editing sees it next to that segment. */
export default function CommentsPanel({ planId, scenario: s, me, activeSeg, onSelectSegment, onShare }: Props) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [text, setText] = useState("");
  const [about, setAbout] = useState<string>(""); // "" = the whole plan
  const [showResolved, setShowResolved] = useState(false);

  const url = planId ? `/api/plans/${planId}/comments` : null;
  const load = () => { if (url) get<Comment[]>(url).then(setComments).catch(() => undefined); };
  useEffect(() => {
    if (!url) return;
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [url]);
  // Follow the segment being edited, so a comment lands where the person is looking.
  useEffect(() => setAbout(activeSeg ?? ""), [activeSeg]);

  async function send() {
    if (!url || !text.trim()) return;
    await post<Comment>(url, { author: me, plan: s.name, segment_id: about || null, text: text.trim() });
    setText("");
    load();
  }

  if (!planId) {
    return (
      <section className="comments">
        <header><h2>Comments</h2></header>
        <p className="hint">Share this plan to let a colleague add their own segments or leave comments for you.</p>
        <button type="button" className="query-btn" onClick={onShare}>Share plan</button>
      </section>
    );
  }

  const mine = comments.filter((c) => c.plan === s.name);
  const shown = mine.filter((c) => showResolved || !c.resolved);
  const label = (id: string | null) => {
    if (id === null) return `Plan ${s.name}`;
    const g = s.segments.find((x) => x.id === id);
    return g ? segmentLabel(g) : `Segment ${id} (deleted)`;
  };
  return (
    <section className="comments">
      <header>
        <h2>Comments</h2>
        {mine.some((c) => c.resolved) && (
          <label className="fresh"><input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} /> Show resolved</label>
        )}
      </header>
      {shown.length === 0 && <p className="hint">No open comments on plan {s.name}.</p>}
      <ul className="thread">
        {shown.map((c) => (
          <li key={c.id} className={c.resolved ? "resolved" : ""}>
            <Avatar p={c.author} small />
            <div>
              <p className="comment-meta">
                <strong>{c.author.name}</strong> on{" "}
                {c.segment_id ? <button type="button" className="link" onClick={() => onSelectSegment(c.segment_id!)}>{label(c.segment_id)}</button> : label(null)}
                {" · "}{ago(c.created_at)}
              </p>
              <p className="comment-text">{c.text}</p>
            </div>
            <button type="button" className="link" onClick={() => patch(`${url}/${c.id}?resolved=${!c.resolved}`, {}).then(() => load())}>
              {c.resolved ? "Reopen" : "Resolve"}
            </button>
          </li>
        ))}
      </ul>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <select value={about} onChange={(e) => setAbout(e.target.value)} aria-label="Comment on">
          <option value="">Whole plan {s.name}</option>
          {s.segments.map((g) => <option key={g.id} value={g.id}>{segmentLabel(g)}</option>)}
        </select>
        <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder={`Comment as ${me.name}…`}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send(); }} />
        <button type="submit" className="query-btn" disabled={!text.trim()}>Comment</button>
      </form>
    </section>
  );
}
