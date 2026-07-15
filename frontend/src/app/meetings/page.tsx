"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import MeetingCard from "@/components/MeetingCard";
import UploadForm from "@/components/UploadForm";
import RecordButton from "@/components/RecordButton";
import { listMeetings, type Meeting } from "@/lib/api";

export default function MeetingsPage() {
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const ms = await listMeetings();
      setMeetings(ms);
      setError(null);
      // Poll while any meeting is still processing (202 background pipeline).
      const busy = ms.some((m) => m.status === "transcribing" || m.status === "uploaded");
      if (busy && !timer.current) {
        timer.current = setInterval(refresh, 4000);
      } else if (!busy && timer.current) {
        clearInterval(timer.current);
        timer.current = null;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load meetings");
    }
  }, []);

  useEffect(() => {
    refresh();
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [refresh]);

  return (
    <>
      <div className="page-header">
        <h1>Meetings</h1>
        <span className="muted">Upload a recording — tasks are extracted automatically</span>
      </div>

      <RecordButton onUploaded={refresh} />
      <UploadForm onUploaded={refresh} />

      {error && <div className="error-banner">Backend unreachable: {error}</div>}
      {meetings === null && !error && (
        <div aria-hidden>
          <div className="shimmer" />
          <div className="shimmer" />
        </div>
      )}
      {meetings && meetings.length === 0 && (
        <div className="empty-state">
          <div className="icon">🎙️</div>
          <div className="title">No meetings yet</div>
          <div className="sub">Record or upload a recording above — transcript, summary, and tasks appear automatically.</div>
        </div>
      )}
      {meetings && meetings.length > 0 && (
        <div className="meeting-list">
          {meetings.map((m) => (
            <MeetingCard key={m.id} meeting={m} onDeleted={refresh} />
          ))}
        </div>
      )}
    </>
  );
}
