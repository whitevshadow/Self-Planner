"use client";

import { useRef, useState } from "react";
import { createMeetingFromText, uploadMeeting } from "@/lib/api";

type Mode = "audio" | "text";

export default function UploadForm({ onUploaded }: { onUploaded: () => void }) {
  const [mode, setMode] = useState<Mode>("audio");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const canSubmit = mode === "audio" ? !!file : text.trim().length > 0;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "audio") {
        await uploadMeeting(file!, title.trim() || undefined);
        setFile(null);
        if (fileRef.current) fileRef.current.value = "";
      } else {
        await createMeetingFromText(text.trim(), title.trim() || undefined);
        setText("");
      }
      setTitle("");
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="upload-card" onSubmit={submit}>
      <div className="upload-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "audio"}
          className={mode === "audio" ? "active" : ""}
          onClick={() => setMode("audio")}
          disabled={busy}
        >
          Upload audio
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "text"}
          className={mode === "text" ? "active" : ""}
          onClick={() => setMode("text")}
          disabled={busy}
        >
          Paste text
        </button>
      </div>

      {mode === "audio" ? (
        <input
          ref={fileRef}
          type="file"
          accept=".mp3,.wav,.m4a"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          disabled={busy}
        />
      ) : (
        <textarea
          className="upload-textarea"
          placeholder="Paste a meeting transcript or your notes. Prefix lines with a name (e.g. “Anish: send the doc”) and speakers are picked up automatically."
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={busy}
          rows={6}
        />
      )}

      <input
        type="text"
        placeholder={mode === "audio" ? "Title (optional — defaults to filename)" : "Title (optional)"}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        disabled={busy}
      />
      <button type="submit" disabled={!canSubmit || busy}>
        {busy ? (mode === "audio" ? "Uploading…" : "Extracting…") : mode === "audio" ? "Upload" : "Extract tasks"}
      </button>
      {busy && (
        <div className="upload-status">
          <span className="spinner" />
          {mode === "audio"
            ? "Uploading… processing continues in the background (watch the status badge)."
            : "Extracting tasks in the background (watch the status badge)."}
        </div>
      )}
      {error && <div className="upload-status error">{error}</div>}
    </form>
  );
}
