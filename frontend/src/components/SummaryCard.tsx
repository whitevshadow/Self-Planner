import type { MeetingDetail } from "@/lib/api";

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

  return (
    <div className="summary-card">
      <h2>Summary</h2>
      <p>{meeting.summary}</p>
      {meeting.decisions && meeting.decisions.length > 0 && (
        <>
          <h3>Key decisions</h3>
          <ul>
            {meeting.decisions.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
