"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import MiniCalendar from "@/components/MiniCalendar";
import TodayColumn from "@/components/TodayColumn";
import {
  confirmTask,
  dismissTask,
  listTasks,
  updateTask,
  type Task,
} from "@/lib/api";
import { formatDue } from "@/lib/dates";

export default function MyTasksPage() {
  const [mine, setMine] = useState<Task[] | null>(null);
  const [inbox, setInbox] = useState<Task[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focusIdx, setFocusIdx] = useState(0);
  const focusedRef = useRef<HTMLDivElement | null>(null);

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

  // Keyboard-driven inbox: j/k move, m = mine, x = not mine. Skips typing fields.
  useEffect(() => {
    const items = inbox ?? [];
    if (items.length === 0) return;
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable))
        return;
      const cur = Math.min(focusIdx, items.length - 1);
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        setFocusIdx(Math.min(items.length - 1, cur + 1));
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        setFocusIdx(Math.max(0, cur - 1));
      } else if (e.key === "m" || e.key === "Enter") {
        e.preventDefault();
        act(items[cur].id, "confirm");
      } else if (e.key === "x") {
        e.preventDefault();
        act(items[cur].id, "dismiss");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [inbox, focusIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the focused inbox card in view as j/k moves through the list.
  useEffect(() => {
    focusedRef.current?.scrollIntoView({ block: "nearest" });
  }, [focusIdx, inbox]);

  async function toggleDone(t: Task) {
    await updateTask(t.id, { status: t.status === "done" ? "open" : "done" });
    refresh();
  }

  const today = new Date().toISOString().slice(0, 10);
  const open = (mine ?? []).filter((t) => t.status === "open");
  const done = (mine ?? []).filter((t) => t.status !== "open");
  const highPriority = open.filter(
    (t) => t.priority === "high" || (t.due_date != null && t.due_date < today)
  );
  const rest = open.filter((t) => !highPriority.includes(t));
  const dueDates = new Set(
    open.flatMap((t) => (t.due_date ? [t.due_date.slice(0, 10)] : []))
  );

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const dateLine = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  const taskRow = (t: Task) => (
    <div className={`mytask ${t.due_date && t.due_date < today ? "overdue" : ""}`} key={t.id}>
      <input type="checkbox" checked={false} onChange={() => toggleDone(t)} title="Mark done" />
      <div className="mytask-info">
        <div className="title">
          {t.title}
          {t.priority && <span className={`prio ${t.priority}`}>{t.priority}</span>}
          {t.at_risk && <span className="prio high" title="Can't be finished before its due date at the current plan">at risk</span>}
        </div>
        <div className="meta">
          {t.due_date ? (
            (() => {
              const d = formatDue(t.due_date);
              return <span className={d.overdue ? "overdue-text" : ""}>{d.label}</span>;
            })()
          ) : (
            "no deadline"
          )}
          {t.assignment_reason && (
            <span className="why-hint" title={t.assignment_reason}>
              {" "}· why me?
            </span>
          )}
        </div>
      </div>
      <Link href={`/meetings/${t.meeting_id}?task=${t.id}`} className="meeting-link">
        open meeting →
      </Link>
    </div>
  );

  return (
    <>
      <div className="hello-hero">
        <h1>{greeting}, Anish 👋</h1>
        <div className="hello-sub">
          {dateLine}
          {mine !== null &&
            ` · ${open.length} open task${open.length === 1 ? "" : "s"}${
              highPriority.length > 0
                ? `, ${highPriority.length} need${highPriority.length === 1 ? "s" : ""} attention`
                : ""
            }`}
        </div>
      </div>

      {error && <div className="error-banner">Backend unreachable: {error}</div>}

      {inbox && inbox.length > 0 && (
        <div className="inbox">
          <h2>
            Maybe mine <span className="inbox-count">{inbox.length}</span>
          </h2>
          <p className="muted">
            Tasks the AI wasn&apos;t sure about — confirm or dismiss.{" "}
            <span className="kbd-hint">
              <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>m</kbd> mine · <kbd>x</kbd> not mine
            </span>
          </p>
          {inbox.map((t, i) => {
            const focused = i === Math.min(focusIdx, inbox.length - 1);
            return (
              <div
                className={`inbox-item ${focused ? "focused" : ""}`}
                key={t.id}
                ref={focused ? focusedRef : undefined}
                onMouseEnter={() => setFocusIdx(i)}
              >
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
                    see context →
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="dash-grid">
        <div>
          {highPriority.length > 0 && (
            <div className="hp-section">
              <h2>
                <span className="hp-flame">⚑</span> High priority ({highPriority.length})
              </h2>
              <div className="mytask-list">{highPriority.map(taskRow)}</div>
            </div>
          )}

          <h2 className="list-title">
            {highPriority.length > 0 ? `Everything else (${rest.length})` : `Open (${open.length})`}
          </h2>
          {mine === null && !error && (
            <div aria-hidden>
              <div className="shimmer" />
              <div className="shimmer" />
              <div className="shimmer" />
            </div>
          )}
          {mine !== null && open.length === 0 && (
            <div className="empty-state">
              <div className="icon">✨</div>
              <div className="title">All clear</div>
              <div className="sub">Record or upload a meeting and tasks will land here on their own.</div>
              <Link href="/meetings">
                <button>Record a meeting</button>
              </Link>
            </div>
          )}
          <div className="mytask-list">{rest.map(taskRow)}</div>

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
        <div>
          <MiniCalendar dueDates={dueDates} />
          <TodayColumn />
        </div>
      </div>
    </>
  );
}
