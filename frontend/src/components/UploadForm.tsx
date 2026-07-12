"use client";

import { useRef, useState } from "react";
import { uploadMeeting } from "@/lib/api";

export default function UploadForm({ onUploaded }: { onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    try {
      await uploadMeeting(file, title.trim() || undefined);
      setFile(null);
      setTitle("");
      if (fileRef.current) fileRef.current.value = "";
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="upload-card" onSubmit={submit}>
      <input
        ref={fileRef}
        type="file"
        accept=".mp3,.wav,.m4a"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        disabled={busy}
      />
      <input
        type="text"
        placeholder="Title (optional — defaults to filename)"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        disabled={busy}
      />
      <button type="submit" disabled={!file || busy}>
        {busy ? "Uploading…" : "Upload"}
      </button>
      {busy && (
        <div className="upload-status">
          <span className="spinner" />
          Uploading… processing continues in the background (watch the status badge).
        </div>
      )}
      {error && <div className="upload-status error">{error}</div>}
    </form>
  );
}
