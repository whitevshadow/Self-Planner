"use client";

import { useState } from "react";

const DOW = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

function ymd(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Month calendar: today highlighted, a dot on days with task due dates. */
export default function MiniCalendar({ dueDates }: { dueDates: Set<string> }) {
  const today = new Date();
  const [view, setView] = useState({ year: today.getFullYear(), month: today.getMonth() });

  const first = new Date(view.year, view.month, 1);
  // Monday-first grid: offset of the 1st from the row start.
  const lead = (first.getDay() + 6) % 7;
  const gridStart = new Date(view.year, view.month, 1 - lead);
  const cells = Array.from({ length: 42 }, (_, i) => {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    return d;
  });

  const monthLabel = first.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const todayKey = ymd(today);

  function shift(delta: number) {
    const m = view.month + delta;
    setView({ year: view.year + Math.floor(m / 12), month: ((m % 12) + 12) % 12 });
  }

  return (
    <div className="mini-cal">
      <div className="mini-cal-head">
        <button onClick={() => shift(-1)} aria-label="Previous month">
          ‹
        </button>
        <span className="month-label">{monthLabel}</span>
        <button onClick={() => shift(1)} aria-label="Next month">
          ›
        </button>
      </div>
      <div className="mini-cal-grid">
        {DOW.map((d) => (
          <span className="dow" key={d}>
            {d}
          </span>
        ))}
        {cells.map((d) => {
          const key = ymd(d);
          const cls = [
            "mini-cal-day",
            d.getMonth() !== view.month ? "other-month" : "",
            key === todayKey ? "today" : "",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <span className={cls} key={key} title={dueDates.has(key) ? "Task due" : undefined}>
              {d.getDate()}
              {dueDates.has(key) && <span className="due-dot" />}
            </span>
          );
        })}
      </div>
    </div>
  );
}
