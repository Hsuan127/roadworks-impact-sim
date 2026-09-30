import { useState } from "react";
import { initials } from "../identity";
import type { Person } from "../types";

interface Props {
  me: Person;
  onRename: (name: string) => void;
  planId: string | null;
  viewers: Person[];
  lastBy: Person | null;
  onShare: () => Promise<string>;
}

export const Avatar = ({ p, small = false }: { p: Person; small?: boolean }) => (
  <span className={small ? "avatar small" : "avatar"} style={{ background: p.color }} title={p.name} aria-label={p.name}>{initials(p.name)}</span>
);

/** Who is here, who I am, and the link that brings someone else into this plan. */
export default function People({ me, onRename, planId, viewers, lastBy, onShare }: Props) {
  const [editing, setEditing] = useState(false);
  const [copied, setCopied] = useState(false);
  const others = viewers.filter((v) => v.name !== me.name);

  async function share() {
    const url = await onShare();
    try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 2500); } catch { /* shown in the address bar anyway */ }
  }

  return (
    <div className="people">
      {planId && others.map((v) => <Avatar key={v.name} p={v} />)}
      {editing ? (
        <input className="me-input" autoFocus defaultValue={me.name} aria-label="Your name"
          onBlur={(e) => { onRename(e.target.value.trim() || me.name); setEditing(false); }}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
      ) : (
        <button type="button" className="me" onClick={() => setEditing(true)} title="Change your name">
          <Avatar p={me} /> <span>{me.name}</span>
        </button>
      )}
      <button type="button" className="share" onClick={share}>{copied ? "Link copied" : planId ? "Copy link" : "Share"}</button>
      {planId && lastBy && lastBy.name !== me.name && <span className="last-edit">Last edit by {lastBy.name}</span>}
    </div>
  );
}
