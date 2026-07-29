"use client";

import { useState } from "react";
import { deleteTask, formatMinutes, updateTask, type ChatTask } from "@/lib/api";
import { formatDue } from "@/lib/dates";

/** Tasks the agent just created, as a live checklist.
 *
 * The tasks are already real — the agent commits them as it goes — so this is a
 * result card, not a confirmation step. Ticking completes a task; Undo deletes
 * it, which is the escape hatch for "that isn't what I meant".
 */
export default function ChatTaskCard({ tasks }: { tasks: ChatTask[] }) {
  const [state, setState] = useState<Record<string, "open" | "done" | "gone">>(
    () => Object.fromEntries(tasks.map((t) => [t.id, t.status === "done" ? "done" : "open"]))
  );
  const [error, setError] = useState<string | null>(null);

  async function toggle(t: ChatTask) {
    const next = state[t.id] === "done" ? "open" : "done";
    setState((s) => ({ ...s, [t.id]: next }));
    try {
      await updateTask(t.id, { status: next });
      setError(null);
    } catch (err) {
      setState((s) => ({ ...s, [t.id]: next === "done" ? "open" : "done" })); // roll back
      setError(err instanceof Error ? err.message : "Could not update that task");
    }
  }

  async function undo(t: ChatTask) {
    if (!confirm(`Remove "${t.title}"? This deletes the task.`)) return;
    const prev = state[t.id];
    setState((s) => ({ ...s, [t.id]: "gone" }));
    try {
      await deleteTask(t.id);
      setError(null);
    } catch (err) {
      setState((s) => ({ ...s, [t.id]: prev }));
      setError(err instanceof Error ? err.message : "Could not remove that task");
    }
  }

  const live = tasks.filter((t) => state[t.id] !== "gone");
  if (live.length === 0) return null;

  return (
    <div className="chat-taskcard">
      <div className="chat-taskcard-head">
        <span className="chat-taskcard-title">
          {live.length === 1 ? "Task added" : `${live.length} tasks added`}
        </span>
        <span className="muted">tick to complete</span>
      </div>

      {live.map((t) => {
        const done = state[t.id] === "done";
        const due = t.due_date ? formatDue(t.due_date) : null;
        return (
          <div className={`chat-taskrow${done ? " done" : ""}`} key={t.id}>
            <input
              type="checkbox"
              checked={done}
              onChange={() => toggle(t)}
              aria-label={done ? `Reopen "${t.title}"` : `Complete "${t.title}"`}
            />
            <div className="chat-taskrow-info">
              <div className="chat-taskrow-title">{t.title}</div>
              <div className="chat-taskrow-meta">
                {t.priority && <span className={`prio ${t.priority}`}>{t.priority}</span>}
                <span className="code-chip">{t.category}</span>
                {due && <span className={due.overdue ? "overdue-text" : ""}>{due.label}</span>}
                {t.estimated_minutes && <span>{formatMinutes(t.estimated_minutes)}</span>}
              </div>
            </div>
            <button className="ghost-danger" onClick={() => undo(t)} title="Delete this task">
              Undo
            </button>
          </div>
        );
      })}

      {error && <div className="chat-taskcard-error">{error}</div>}
    </div>
  );
}
