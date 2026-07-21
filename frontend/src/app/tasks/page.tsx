"use client";

import { useCallback, useEffect, useState } from "react";
import TaskTable from "@/components/TaskTable";
import { listTasks, type Task } from "@/lib/api";

export default function MyTasksPage() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [status, setStatus] = useState("open");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      // Only what I actually own — tasks belonging to other people live on their
      // meeting page, and are taken on from there via the checkboxes.
      setTasks(await listTasks({ assignment: "mine", status: status || undefined }));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tasks");
    }
  }, [status]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <>
      <div className="page-header">
        <h1>My tasks</h1>
        <span className="muted">{tasks ? `${tasks.length} task${tasks.length === 1 ? "" : "s"}` : ""}</span>
      </div>

      <div className="filter-bar">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          aria-label="Filter by status"
        >
          <option value="open">open</option>
          <option value="done">done</option>
          <option value="dropped">dropped</option>
          <option value="">all statuses</option>
        </select>
        {tasks && (
          <span className="filter-count">
            {tasks.length} shown
          </span>
        )}
      </div>

      {error && <div className="error-banner">{error}</div>}
      {tasks === null && !error && <div className="empty">Loading…</div>}
      {tasks && tasks.length === 0 && (
        <div className="empty">
          Nothing assigned to you yet. Open a meeting and tick the tasks you want to take on.
        </div>
      )}
      {tasks && tasks.length > 0 && <TaskTable tasks={tasks} onChanged={refresh} showMeetingLink />}
    </>
  );
}
