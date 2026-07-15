"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Renders the LLM-generated meeting minutes (Markdown) as formatted HTML. */
export default function MeetingNotes({ notes }: { notes: string }) {
  return (
    <div className="notes-body markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{notes}</ReactMarkdown>
    </div>
  );
}
