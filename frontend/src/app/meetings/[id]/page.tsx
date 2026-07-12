"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import SpeakerMapBar from "@/components/SpeakerMapBar";
import SummaryCard from "@/components/SummaryCard";
import TaskTable from "@/components/TaskTable";
import TranscriptView from "@/components/TranscriptView";
import {
  formatDuration,
  getMeeting,
  isProcessing,
  reExtract,
  type MeetingDetail,
} from "@/lib/api";

const STAGE_LABELS: Record<string, string> = {
  transcribing: "Transcribing audio…",
  diarizing: "Detecting speakers…",
  extracting: "Extracting summary & tasks…",
};

export default function MeetingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const search = useSearchParams();
  const focusTaskId = search.get("task");

  const [meeting, setMeeting] = useState<MeetingDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [flashIdx, setFlashIdx] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const m = await getMeeting(id);
      setMeeting(m);
      setError(null);
      if (isProcessing(m) && !timer.current) {
        timer.current = setInterval(refresh, 3000);
      } else if (!isProcessing(m) && timer.current) {
        clearInterval(timer.current);
        timer.current = null;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load meeting");
    }
  }, [id]);

  useEffect(() => {
    refresh();
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [refresh]);

  // Jump to the source segment when arriving via ?task= or clicking a task row.
  useEffect(() => {
    if (meeting && focusTaskId) {
      const t = meeting.tasks.find((x) => x.id === focusTaskId);
      if (t?.segment_idx != null) setFlashIdx(t.segment_idx);
    }
  }, [meeting?.id, focusTaskId]); // eslint-disable-line react-hooks/exhaustive-deps

  const myHighlights = useMemo(() => {
    if (!meeting) return new Set<number>();
    return new Set(
      meeting.tasks
        .filter((t) => t.assignment === "mine" && t.segment_idx != null)
        .map((t) => t.segment_idx as number)
    );
  }, [meeting]);

  async function handleReExtract() {
    if (
      !confirm(
        "Re-run summary, task extraction, and classification? Unedited tasks will be replaced; your edits and inbox decisions are preserved."
      )
    )
      return;
    setExtracting(true);
    try {
      setMeeting(await reExtract(id));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Re-extraction failed");
    } finally {
      setExtracting(false);
    }
  }

  if (error && !meeting) return <div className="error-banner">{error}</div>;
  if (!meeting) return <div className="empty">Loading…</div>;

  const stage =
    meeting.status === "transcribing" || meeting.status === "uploaded"
      ? "transcribing"
      : meeting.diarize_status === "running"
        ? "diarizing"
        : meeting.extract_status === "running" || (meeting.status === "done" && meeting.extract_status === "pending")
          ? "extracting"
          : null;

  return (
    <>
      <Link href="/meetings" className="back-link">
        ← All meetings
      </Link>
      <div className="page-header" style={{ marginTop: "0.75rem" }}>
        <h1>{meeting.title}</h1>
        <span className={`badge ${meeting.status}`}>{meeting.status}</span>
      </div>
      <div className="muted">
        {new Date(meeting.created_at).toLocaleString()} · {formatDuration(meeting.duration_sec)} ·{" "}
        {meeting.filename}
        {meeting.diarize_status === "skipped" && " · diarization skipped"}
        {meeting.diarize_status === "failed" && " · diarization failed"}
      </div>

      {stage && (
        <div className="summary-card">
          <div className="upload-status">
            <span className="spinner" />
            {STAGE_LABELS[stage]}
          </div>
        </div>
      )}

      {meeting.status === "failed" && (
        <div className="error-banner">Transcription failed: {meeting.error ?? "unknown error"}</div>
      )}

      {meeting.status === "done" && (
        <>
          {meeting.diarize_status === "done" && (
            <SpeakerMapBar meeting={meeting} onSaved={setMeeting} />
          )}
          {(meeting.diarize_status === "failed" || meeting.diarize_status === "skipped") && (
            <div className="notice-banner">
              Automatic speaker detection {meeting.diarize_status === "failed" ? "failed" : "was skipped"} —
              you can label speakers manually next to each transcript line below.
            </div>
          )}

          {!stage && <SummaryCard meeting={extracting ? { ...meeting, extract_status: "running" } : meeting} />}

          {meeting.extract_status === "failed" && !extracting && (
            <div className="error-banner">
              Extraction failed: {meeting.extract_error ?? "unknown error"}
            </div>
          )}
          {error && <div className="error-banner">{error}</div>}

          {!stage && (
            <>
              <div className="section-header">
                <h2>Tasks</h2>
                <button onClick={handleReExtract} disabled={extracting}>
                  {extracting ? "Extracting…" : "Re-extract"}
                </button>
              </div>
              <TaskTable
                tasks={meeting.tasks}
                onChanged={refresh}
                onRowClick={(t) => t.segment_idx != null && setFlashIdx(t.segment_idx)}
              />
            </>
          )}

          <div className="section-header">
            <h2>Transcript</h2>
            {myHighlights.size > 0 && <span className="muted">highlighted = produced my tasks</span>}
          </div>
          <TranscriptView
            meeting={meeting}
            highlightIdxs={myHighlights}
            flashIdx={flashIdx}
            manualLabeling={meeting.diarize_status === "failed" || meeting.diarize_status === "skipped"}
            onChanged={setMeeting}
          />
        </>
      )}
    </>
  );
}
