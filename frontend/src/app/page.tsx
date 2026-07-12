"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import TodayColumn from "@/components/TodayColumn";
import {
  confirmTask,
  dismissTask,
  listTasks,
  updateTask,
  type Task,
} from "@/lib/api";

export default function MyTasksPage() {
  const [mine, setMine] = useState<Task[] | null>(null);
  const [inbox, setInbox] = useState<Task[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [m, i] = await Promise.all([
        listTasks({ assignment: "mine" }),
        listTasks({ assignment: "maybe", status: "open" }),
      ]);
      setMine(m);
      setInbox(i);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tasks");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function act(id: string, action: "confirm" | "dismiss") {
    await (action === "confirm" ? confirmTask(id) : dismissTask(id));
    refresh();
  }

  async function toggleDone(t: Task) {
    await updateTask(t.id, { status: t.status === "done" ? "open" : "done" });
    refresh();
  }

  const today = new Date().toISOString().slice(0, 10);
  const open = (mine ?? []).filter((t) => t.status === "open");
  const done = (mine ?? []).filter((t) => t.status !== "open");

  return (
    <>
      <div className="page-header">
        <h1>My Tasks</h1>
        <nav className="nav-links">
          <Link href="/meetings">Meetings</Link>
          <Link href="/tasks">All tasks</Link>
          <Link href="/chat">Chat</Link>
          <Link href="/gantt">Gantt</Link>
          <Link href="/settings/people">People</Link>
          <Link href="/settings/availability">Availability</Link>
        </nav>
      </div>

      {error && <div className="error-banner">Backend unreachable: {error}</div>}

      {inbox && inbox.length > 0 && (
        <div className="inbox">
          <h2>
            Maybe mine <span className="inbox-count">{inbox.length}</span>
          </h2>
          <p className="muted">Tasks the AI wasn&apos;t sure about — confirm or dismiss:</p>
          {inbox.map((t) => (
            <div className="inbox-item" key={t.id}>
              <div className="inbox-info">
                <div className="title">{t.title}</div>
                {t.assignment_reason && <div className="reason">{t.assignment_reason}</div>}
                {t.source_quote && <div className="quote">“{t.source_quote}”</div>}
              </div>
              <div className="inbox-actions">
                <button onClick={() => act(t.id, "confirm")}>Mine</button>
                <button className="ghost-danger" onClick={() => act(t.id, "dismiss")}>
                  Not mine
                </button>
                <Link href={`/meetings/${t.meeting_id}?task=${t.id}`} className="meeting-link">
                  context →
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="dash-grid">
        <div>
      <h2 className="list-title">Open ({open.length})</h2>
      {mine === null && !error && <div className="empty">Loading…</div>}
      {mine !== null && open.length === 0 && (
        <div className="empty">
          No open tasks assigned to you. Upload a meeting on the{" "}
          <Link href="/meetings" style={{ textDecoration: "underline" }}>
            Meetings page
          </Link>
          .
        </div>
      )}
      <div className="mytask-list">
        {open.map((t) => (
          <div className={`mytask ${t.due_date && t.due_date < today ? "overdue" : ""}`} key={t.id}>
            <input type="checkbox" checked={false} onChange={() => toggleDone(t)} title="Mark done" />
            <div className="mytask-info">
              <div className="title">
                {t.title}
                {t.priority && <span className={`prio ${t.priority}`}>{t.priority}</span>}
              </div>
              <div className="meta">
                {t.due_date ? (
                  <span className={t.due_date < today ? "overdue-text" : ""}>
                    due {t.due_date}
                    {t.due_date < today ? " — overdue" : ""}
                  </span>
                ) : (
                  "no deadline"
                )}
                {t.assignment_reason && <span title={t.assignment_reason}> · why?</span>}
              </div>
            </div>
            <Link href={`/meetings/${t.meeting_id}?task=${t.id}`} className="meeting-link">
              meeting →
            </Link>
          </div>
        ))}
      </div>

      {done.length > 0 && (
        <>
          <h2 className="list-title muted">Done / dropped ({done.length})</h2>
          <div className="mytask-list dim">
            {done.map((t) => (
              <div className="mytask" key={t.id}>
                <input type="checkbox" checked onChange={() => toggleDone(t)} title="Reopen" />
                <div className="mytask-info">
                  <div className="title strike">{t.title}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
        </div>
        <TodayColumn />
      </div>
    </>
  );
}
