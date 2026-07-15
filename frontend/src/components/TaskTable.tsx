"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { assignTasksToMe, deleteTask, formatMinutes, updateTask, type Task } from "@/lib/api";

const PRIORITIES = ["", "high", "medium", "low"] as const;
const STATUSES = ["open", "done", "dropped"] as const;

// Triage runs server-side after the assignment commits, so the enriched fields
// arrive a beat later. Poll until they do, then give up rather than spin forever
// on a gateway that is refusing to answer.
const TRIAGE_POLL_MS = 3000;
const TRIAGE_TIMEOUT_MS = 90_000;

/** Inline-editable task table.
 * `showMeetingLink` adds a column linking to the source meeting.
 * `selectable` adds a checkbox column and a bulk "Assign to me" bar. */
export default function TaskTable({
  tasks,
  onChanged,
  showMeetingLink = false,
  selectable = false,
  onRowClick,
}: {
  tasks: Task[];
  onChanged: () => void;
  showMeetingLink?: boolean;
  selectable?: boolean;
  onRowClick?: (t: Task) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [assigning, setAssigning] = useState(false);
  const [triaging, setTriaging] = useState<Set<string>>(new Set());
  const triageDeadline = useRef(0);

  // Wait for the background triage to land priority/duration/deadline on the
  // tasks I just took on, refetching until every one of them has a priority.
  useEffect(() => {
    if (triaging.size === 0) return;
    const pending = tasks.filter((t) => triaging.has(t.id) && t.priority === null);
    if (pending.length === 0) {
      setTriaging(new Set());
      return;
    }
    if (Date.now() > triageDeadline.current) {
      setTriaging(new Set());
      setError(
        "Assigned to you, but the planner could not reach the model to set priority and duration. " +
          "You can fill them in by hand, or re-assign to retry."
      );
      return;
    }
    const timer = setTimeout(onChanged, TRIAGE_POLL_MS);
    return () => clearTimeout(timer);
  }, [tasks, triaging, onChanged]);

  async function patch(id: string, fields: Partial<Task>) {
    try {
      await updateTask(id, fields);
      setError(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  }

  async function remove(id: string, title: string) {
    if (!confirm(`Delete task "${title}"?`)) return;
    await deleteTask(id);
    onChanged();
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function assignSelected() {
    const ids = [...selected];
    setAssigning(true);
    try {
      await assignTasksToMe(ids);
      setSelected(new Set());
      setError(null);
      triageDeadline.current = Date.now() + TRIAGE_TIMEOUT_MS;
      setTriaging(new Set(ids));
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not assign these tasks to you");
    } finally {
      setAssigning(false);
    }
  }

  if (tasks.length === 0) return <div className="empty">No tasks.</div>;

  const allSelected = selectable && tasks.length > 0 && selected.size === tasks.length;

  return (
    <>
      {error && <div className="error-banner">{error}</div>}

      {selectable && selected.size > 0 && (
        <div className="bulk-bar">
          <span>
            {selected.size} task{selected.size === 1 ? "" : "s"} selected
          </span>
          <button onClick={assignSelected} disabled={assigning}>
            {assigning ? "Assigning…" : "Assign to me"}
          </button>
          <button className="ghost" onClick={() => setSelected(new Set())} disabled={assigning}>
            Clear
          </button>
        </div>
      )}

      {selectable && triaging.size > 0 && (
        <div className="bulk-bar">
          <span className="spinner" />
          <span>
            Working out priority, duration and deadline for {triaging.size} task
            {triaging.size === 1 ? "" : "s"}…
          </span>
        </div>
      )}

      <div className="task-table-wrap">
        <table className="task-table">
          <thead>
            <tr>
              {selectable && (
                <th className="check-cell">
                  <input
                    type="checkbox"
                    aria-label="Select all tasks"
                    checked={allSelected}
                    onChange={() =>
                      setSelected(allSelected ? new Set() : new Set(tasks.map((t) => t.id)))
                    }
                  />
                </th>
              )}
              <th>Task</th>
              <th>Who</th>
              <th>Owner</th>
              <th>Start</th>
              <th>Due</th>
              <th>Est.</th>
              <th>Priority</th>
              <th>Status</th>
              {showMeetingLink && <th>Meeting</th>}
              <th></th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr
                key={t.id}
                className={t.status !== "open" ? "task-closed" : ""}
                onClick={() => onRowClick?.(t)}
                style={onRowClick && t.segment_idx != null ? { cursor: "pointer" } : undefined}
              >
                {selectable && (
                  <td className="check-cell" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      aria-label={`Select "${t.title}"`}
                      checked={selected.has(t.id)}
                      onChange={() => toggle(t.id)}
                    />
                  </td>
                )}
                <td className="task-title-cell">
                  <EditableText value={t.title} onSave={(v) => patch(t.id, { title: v })} />
                  {t.source_quote && <div className="quote" title={t.source_quote}>“{t.source_quote}”</div>}
                  {t.edited && <span className="edited-flag" title="Edited by you — protected from re-extraction">edited</span>}
                </td>
                <td>
                  <span
                    className={`assign-badge ${t.assignment}`}
                    title={t.assignment_reason ?? undefined}
                  >
                    {t.assignment}
                  </span>
                </td>
                <td>
                  <EditableText
                    value={t.owner ?? ""}
                    placeholder="—"
                    onSave={(v) => patch(t.id, { owner: v || null })}
                  />
                </td>
                <td>
                  <input
                    type="date"
                    className="cell-input"
                    value={t.start_date ?? ""}
                    onChange={(e) => patch(t.id, { start_date: e.target.value || null })}
                  />
                </td>
                <td>
                  <input
                    type="date"
                    className="cell-input"
                    value={t.due_date ?? ""}
                    onChange={(e) => patch(t.id, { due_date: e.target.value || null })}
                  />
                </td>
                <td className="est-cell" title={t.estimate_source === "user" ? "Your estimate" : "Estimated by the planner"}>
                  {formatMinutes(t.estimated_minutes)}
                </td>
                <td>
                  <select
                    className="cell-input"
                    value={t.priority ?? ""}
                    onChange={(e) => patch(t.id, { priority: (e.target.value || null) as Task["priority"] })}
                  >
                    {PRIORITIES.map((p) => (
                      <option key={p} value={p}>
                        {p || "—"}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    className="cell-input"
                    value={t.status}
                    onChange={(e) => patch(t.id, { status: e.target.value as Task["status"] })}
                  >
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </td>
                {showMeetingLink && (
                  <td>
                    <Link href={`/meetings/${t.meeting_id}`} className="meeting-link">
                      open →
                    </Link>
                  </td>
                )}
                <td>
                  <button className="ghost-danger" onClick={() => remove(t.id, t.title)}>
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function EditableText({
  value,
  onSave,
  placeholder,
}: {
  value: string;
  onSave: (v: string) => void;
  placeholder?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  if (!editing) {
    return (
      <span
        className={`editable ${!value ? "placeholder" : ""}`}
        onClick={() => {
          setDraft(value);
          setEditing(true);
        }}
        title="Click to edit"
      >
        {value || placeholder || "—"}
      </span>
    );
  }
  return (
    <input
      className="cell-input"
      autoFocus
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        setEditing(false);
        if (draft.trim() !== value) onSave(draft.trim());
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") {
          setDraft(value);
          setEditing(false);
        }
      }}
    />
  );
}
