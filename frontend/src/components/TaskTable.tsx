"use client";

import Link from "next/link";
import { useState } from "react";
import { deleteTask, updateTask, type Task } from "@/lib/api";

const PRIORITIES = ["", "high", "medium", "low"] as const;
const STATUSES = ["open", "done", "dropped"] as const;

/** Inline-editable task table. `showMeetingLink` adds a column linking to the source meeting. */
export default function TaskTable({
  tasks,
  onChanged,
  showMeetingLink = false,
  onRowClick,
}: {
  tasks: Task[];
  onChanged: () => void;
  showMeetingLink?: boolean;
  onRowClick?: (t: Task) => void;
}) {
  const [error, setError] = useState<string | null>(null);

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

  if (tasks.length === 0) return <div className="empty">No tasks.</div>;

  return (
    <>
      {error && <div className="error-banner">{error}</div>}
      <div className="task-table-wrap">
        <table className="task-table">
          <thead>
            <tr>
              <th>Task</th>
              <th>Who</th>
              <th>Owner</th>
              <th>Due</th>
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
                    value={t.due_date ?? ""}
                    onChange={(e) => patch(t.id, { due_date: e.target.value || null })}
                  />
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
