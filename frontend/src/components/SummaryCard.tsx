"use client";

import type { MeetingDetail } from "@/lib/api";
import CopyButton from "./CopyButton";
import MeetingNotes from "./MeetingNotes";

export default function SummaryCard({ meeting }: { meeting: MeetingDetail }) {
  if (meeting.extract_status === "running" || meeting.extract_status === "pending") {
    return (
      <div className="summary-card">
        <div className="upload-status">
          <span className="spinner" />
          Generating summary and extracting tasks…
        </div>
      </div>
    );
  }

  if (!meeting.summary && meeting.extract_status === "failed") return null;
  if (!meeting.summary) return null;

  const decisions = meeting.decisions ?? [];
  const clipboardText = [
    meeting.summary,
    decisions.length > 0 ? "\nKey decisions:\n" + decisions.map((d) => `- ${d}`).join("\n") : "",
  ]
    .join("\n")
    .trim();

  return (
    <div className="summary-card">
      <div className="section-header" style={{ margin: "0 0 0.4rem" }}>
        <h2 style={{ margin: 0 }}>Summary</h2>
        <CopyButton text={clipboardText} label="Copy summary" />
      </div>
      <p>{meeting.summary}</p>
      {decisions.length > 0 && (
        <>
          <h3>Key decisions</h3>
          <ul>
            {decisions.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </>
      )}
      {meeting.notes && (
        <details className="notes-details" open>
          <summary>Full meeting notes</summary>
          <MeetingNotes notes={meeting.notes} />
        </details>
      )}
    </div>
  );
}
