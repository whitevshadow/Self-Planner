"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import SpeakerMapBar from "@/components/SpeakerMapBar";
import SummaryCard from "@/components/SummaryCard";
import TaskTable from "@/components/TaskTable";
import TranscriptView from "@/components/TranscriptView";
import {
  audioUrl,
  formatDuration,
  getMeeting,
  isProcessing,
  reExtract,
  reTranscribe,
  type MeetingDetail,
} from "@/lib/api";

// Longest plausible pipeline run (large-v3 on a long recording) before we treat
// a still-"running" meeting as hung rather than slow.
const POLL_TIMEOUT_MS = 20 * 60 * 1000;

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
  const [stalled, setStalled] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollingSince = useRef<number | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const seekAudio = useCallback((sec: number, play: boolean) => {
    const el = audioRef.current;
    if (!el) return;
    el.currentTime = sec;
    if (play) el.play().catch(() => {});
  }, []);

  const stopPolling = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    pollingSince.current = null;
  }, []);

  const refresh = useCallback(async () => {
    try {
      const m = await getMeeting(id);
      setMeeting(m);
      setError(null);
      if (isProcessing(m)) {
        pollingSince.current ??= Date.now();
        // A stage that hangs while the server stays up would otherwise poll
        // forever. Give up after POLL_TIMEOUT_MS and offer a retry instead.
        if (Date.now() - pollingSince.current > POLL_TIMEOUT_MS) {
          stopPolling();
          setStalled(true);
        } else if (!timer.current) {
          timer.current = setInterval(refresh, 3000);
        }
      } else {
        stopPolling();
        setStalled(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load meeting");
    }
  }, [id, stopPolling]);

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

  // Move the audio playhead (without auto-playing) to whatever segment is flashed.
  useEffect(() => {
    if (flashIdx == null || !meeting?.has_audio) return;
    const seg = meeting.segments.find((s) => s.idx === flashIdx);
    if (seg) seekAudio(seg.start_sec, false);
  }, [flashIdx, meeting?.id, meeting?.has_audio, seekAudio]); // eslint-disable-line react-hooks/exhaustive-deps

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
      // 202: extraction runs in the background — start polling for progress.
      setMeeting(await reExtract(id));
      setError(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Re-extraction failed");
    } finally {
      setExtracting(false);
    }
  }

  async function handleReTranscribe() {
    if (
      !confirm(
        "Re-transcribe the audio and re-run the whole pipeline (speakers, summary, tasks)? " +
          "The transcript and speaker labels will be replaced; your task edits and inbox decisions are preserved."
      )
    )
      return;
    try {
      // 202: the full pipeline runs in the background — polling takes over.
      setStalled(false);
      pollingSince.current = null;
      setMeeting(await reTranscribe(id));
      setError(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Re-transcription failed");
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

      {stalled && (
        <div className="error-banner">
          This meeting has been stuck on “{stage ? STAGE_LABELS[stage] : "processing"}” for over 20
          minutes, so it&apos;s probably not coming back — the server may have restarted mid-run.{" "}
          <button onClick={handleReTranscribe}>Re-transcribe</button>
        </div>
      )}

      {stage && !stalled && (
        <div className="summary-card">
          <div className="upload-status">
            <span className="spinner" />
            {STAGE_LABELS[stage]}
          </div>
          {stage === "extracting" && meeting.extract_progress && meeting.extract_progress.total > 0 && (
            <div className="progress-row">
              <div className="progress-track">
                <div
                  className="progress-fill"
                  style={{
                    width: `${Math.round((meeting.extract_progress.done / meeting.extract_progress.total) * 100)}%`,
                  }}
                />
              </div>
              <span className="muted">
                {meeting.extract_progress.stage === "summary"
                  ? "Summarizing"
                  : meeting.extract_progress.stage === "extract"
                    ? "Extracting tasks"
                    : "Writing meeting notes"}{" "}
                — batch {Math.min(meeting.extract_progress.done + 1, meeting.extract_progress.total)} of{" "}
                {meeting.extract_progress.total}
              </span>
            </div>
          )}
        </div>
      )}

      {meeting.status === "failed" && (
        <div className="error-banner">
          Transcription failed: {meeting.error ?? "unknown error"}{" "}
          <button onClick={handleReTranscribe}>Retry</button>
        </div>
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
                <button onClick={handleReTranscribe} disabled={extracting} title="Re-run transcription, speaker detection, summary and tasks from the original audio">
                  Re-transcribe
                </button>
              </div>
              <p className="muted">
                Tick any task to take it on yourself — it gets a priority, a duration and a deadline,
                and shows up under My Tasks.
              </p>
              <TaskTable
                tasks={meeting.tasks}
                onChanged={refresh}
                selectable
                onRowClick={(t) => t.segment_idx != null && setFlashIdx(t.segment_idx)}
              />
            </>
          )}

          <div className="section-header">
            <h2>Transcript</h2>
            {myHighlights.size > 0 && <span className="muted">highlighted = produced my tasks</span>}
          </div>
          {meeting.has_audio && (
            <audio ref={audioRef} className="meeting-audio" controls preload="metadata" src={audioUrl(meeting.id)} />
          )}
          <TranscriptView
            meeting={meeting}
            highlightIdxs={myHighlights}
            flashIdx={flashIdx}
            onPlaySegment={meeting.has_audio ? (sec) => seekAudio(sec, true) : undefined}
            manualLabeling={meeting.diarize_status === "failed" || meeting.diarize_status === "skipped"}
            onChanged={setMeeting}
          />
        </>
      )}
    </>
  );
}
