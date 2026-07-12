"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import TaskTable from "@/components/TaskTable";
import { listTasks, type Task } from "@/lib/api";

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [owner, setOwner] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setTasks(
        await listTasks({ owner: owner.trim() || undefined, status: status || undefined })
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tasks");
    }
  }, [owner, status]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <>
      <Link href="/" className="back-link">
        ← My tasks
      </Link>
      <div className="page-header" style={{ marginTop: "0.75rem" }}>
        <h1>All tasks</h1>
        <span className="muted">{tasks ? `${tasks.length} task${tasks.length === 1 ? "" : "s"}` : ""}</span>
      </div>

      <div className="filters">
        <input
          type="text"
          placeholder="Filter by owner…"
          value={owner}
          onChange={(e) => setOwner(e.target.value)}
        />
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="open">open</option>
          <option value="done">done</option>
          <option value="dropped">dropped</option>
        </select>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {tasks === null && !error && <div className="empty">Loading…</div>}
      {tasks && <TaskTable tasks={tasks} onChanged={refresh} showMeetingLink />}
    </>
  );
}
