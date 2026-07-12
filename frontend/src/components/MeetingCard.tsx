"use client";

import Link from "next/link";
import { deleteMeeting, formatDuration, type Meeting } from "@/lib/api";

export default function MeetingCard({
  meeting,
  onDeleted,
}: {
  meeting: Meeting;
  onDeleted: () => void;
}) {
  async function handleDelete(e: React.MouseEvent) {
    e.preventDefault();
    if (!confirm(`Delete "${meeting.title}" and its transcript?`)) return;
    await deleteMeeting(meeting.id);
    onDeleted();
  }

  return (
    <Link href={`/meetings/${meeting.id}`} className="meeting-card">
      <div className="info">
        <div className="title">{meeting.title}</div>
        <div className="meta">
          {new Date(meeting.created_at).toLocaleString()} · {formatDuration(meeting.duration_sec)}
        </div>
      </div>
      <span className={`badge ${meeting.status}`}>{meeting.status}</span>
      <button className="ghost-danger" onClick={handleDelete}>
        Delete
      </button>
    </Link>
  );
}
