import { useEffect, useState } from "react";

/** Shows whether a module just recalculated or kept its previous result. */
export default function Freshness({ updatedAt, loading }: { updatedAt: number | null; loading: boolean }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);
  if (loading) return <span className="fresh busy">Recalculating</span>;
  if (!updatedAt) return null;
  const secs = Math.round((Date.now() - updatedAt) / 1000);
  return secs < 3 ? <span className="fresh new">Updated</span> : <span className="fresh">Unchanged</span>;
}
