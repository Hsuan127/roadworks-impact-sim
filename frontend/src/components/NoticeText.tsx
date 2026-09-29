import { Fragment } from "react";

/** Minimal, safe renderer for the notice: '# ' headings, **bold**, blank-line paragraphs. No HTML injection. */
function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part}</Fragment>,
  );
}

export default function NoticeText({ markdown }: { markdown: string }) {
  const blocks = markdown.split(/\n{2,}/).map((b) => b.trim()).filter(Boolean);
  return (
    <div className="notice">
      {blocks.map((b, i) =>
        b.startsWith("# ") ? <h3 key={i}>{inline(b.slice(2))}</h3> : <p key={i}>{inline(b)}</p>,
      )}
    </div>
  );
}
