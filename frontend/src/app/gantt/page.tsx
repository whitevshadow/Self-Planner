"use client";

import { useEffect, useRef, useState } from "react";
import { listTasks, type Task } from "@/lib/api";
import "./gantt.css";

export default function GanttPage() {
  const ref = useRef<HTMLDivElement>(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"Day" | "Week" | "Month">("Day");

  useEffect(() => {
    listTasks({ assignment: "mine" })
      .then(setTasks)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load tasks"));
  }, []);

  useEffect(() => {
    if (!tasks || !ref.current) return;
    const bars = tasks
      .filter((t) => t.status === "open" && (t.start_date || t.due_date))
      .map((t) => {
        const start = t.start_date ?? t.due_date!;
        const end = t.due_date ?? t.start_date!;
        return {
          id: t.id,
          name: t.title + (t.at_risk ? " ⚠" : ""),
          start,
          end: end >= start ? end : start,
          progress: t.progress,
          dependencies: "",
          custom_class: t.at_risk ? "gantt-risk" : "",
        };
      });
    if (bars.length === 0) return;

    ref.current.innerHTML = "";
    import("frappe-gantt").then(({ default: Gantt }) => {
      if (!ref.current) return;
      new Gantt(ref.current, bars, {
        view_mode: mode,
        readonly: true,
        today_button: true,
      });
    });
  }, [tasks, mode]);

  const hasBars = tasks?.some((t) => t.status === "open" && (t.start_date || t.due_date));

  return (
    <>
      <div className="page-header">
        <h1>Gantt</h1>
        <span className="muted">Open tasks laid out from start date to due date</span>
      </div>

      <div className="filters">
        {(["Day", "Week", "Month"] as const).map((m) => (
          <button key={m} className={mode === m ? "" : "mini ghost"} onClick={() => setMode(m)}>
            {m}
          </button>
        ))}
      </div>

      {error && <div className="error-banner">{error}</div>}
      {tasks && !hasBars && (
        <div className="empty">
          No plannable tasks with dates yet. Run a plan from the dashboard first — bars span start date →
          due date with progress fill.
        </div>
      )}
      <div className="gantt-wrap">
        <div ref={ref} />
      </div>
    </>
  );
}
