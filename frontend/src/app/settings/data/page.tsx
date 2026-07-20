"use client";

import { useState } from "react";
import { exportUrl } from "@/lib/api";

export default function DataBackupPage() {
  const [downloading, setDownloading] = useState(false);

  // Fetch as a blob so we can surface backend errors instead of navigating away,
  // and so the click reliably triggers a Save dialog with the server's filename.
  async function download() {
    setDownloading(true);
    try {
      const res = await fetch(exportUrl());
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const blob = await res.blob();
      const disposition = res.headers.get("content-disposition") ?? "";
      const match = disposition.match(/filename="?([^"]+)"?/);
      const name = match?.[1] ?? "self-planner-export.zip";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Export failed");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Data &amp; Backup</h1>
        <span className="muted">Everything the app knows lives on your machine — take it with you</span>
      </div>

      <div className="summary-card">
        <h2 style={{ marginTop: 0 }}>Export everything</h2>
        <p className="muted">
          Downloads a <code>.zip</code> containing a full structured backup (meetings &amp;
          transcripts, tasks, your plan, people and settings) plus a readable Markdown file per
          meeting — summary, decisions, your tasks and the transcript.
        </p>
        <button onClick={download} disabled={downloading}>
          {downloading ? "Preparing…" : "Download backup (.zip)"}
        </button>
      </div>

      <div className="summary-card" style={{ marginTop: "1rem" }}>
        <h2 style={{ marginTop: 0 }}>Backing up audio &amp; the database</h2>
        <p className="muted">
          The export keeps things light and leaves out the raw recordings. To back up the audio
          files and the full database directly:
        </p>
        <pre className="backup-pre">
{`# Raw audio (MinIO client)
mc cp --recursive local/meetings-audio ./audio-backup

# Full database
pg_dump self_planner > self_planner.sql`}
        </pre>
        <p className="muted">
          Both the Postgres and MinIO Docker volumes already persist across restarts — this is your
          off-machine insurance.
        </p>
      </div>
    </>
  );
}
