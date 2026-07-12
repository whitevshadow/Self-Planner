"use client";

import { useCallback, useEffect, useState } from "react";
import {
  formatTimeHM,
  patchBlock,
  planToday,
  runPlan,
  type DayBlock,
  type PlanWarning,
} from "@/lib/api";

export default function TodayColumn() {
  const [blocks, setBlocks] = useState<DayBlock[] | null>(null);
  const [warnings, setWarnings] = useState<PlanWarning[]>([]);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setBlocks(await planToday());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load plan");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function plan() {
    setPlanning(true);
    setError(null);
    try {
      const r = await runPlan();
      setBlocks(r.today);
      setWarnings(r.warnings);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Planning failed");
    } finally {
      setPlanning(false);
    }
  }

  async function setStatus(b: DayBlock, status: DayBlock["status"]) {
    await patchBlock(b.id, { status });
    refresh();
  }

  return (
    <div className="today-col">
      <div className="section-header" style={{ margin: "0 0 0.6rem" }}>
        <h2>Today</h2>
        <button onClick={plan} disabled={planning}>
          {planning ? "Planning…" : "Replan"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {warnings.length > 0 && (
        <div className="warn-list">
          {warnings.map((w, i) => (
            <div className="warn-item" key={i}>
              ⚠ <strong>{w.title}</strong>: {w.detail}
            </div>
          ))}
        </div>
      )}

      {blocks === null && !error && <div className="empty">Loading…</div>}
      {blocks && blocks.length === 0 && (
        <div className="empty">
          Nothing scheduled today. Hit <em>Replan</em> to build the day from your open tasks.
        </div>
      )}

      <div className="block-list">
        {blocks?.map((b) => (
          <div className={`block ${b.status} ${b.at_risk ? "risk" : ""}`} key={b.id}>
            <span className="block-time">
              {formatTimeHM(b.start_at)}–{formatTimeHM(b.end_at)}
            </span>
            <div className="block-info">
              <div className="title">
                {b.task_title}
                {b.pinned && <span title="Pinned — replans won't move it"> 📌</span>}
                {b.at_risk && <span className="prio high" style={{ marginLeft: "0.4rem" }}>at risk</span>}
              </div>
              <div className="meta">
                {b.category}
                {b.priority ? ` · ${b.priority}` : ""}
              </div>
            </div>
            <div className="block-actions">
              {b.status === "planned" && (
                <button className="mini" onClick={() => setStatus(b, "in_progress")}>
                  Start
                </button>
              )}
              {b.status === "in_progress" && (
                <button className="mini" onClick={() => setStatus(b, "done")}>
                  Done
                </button>
              )}
              {(b.status === "planned" || b.status === "in_progress") && (
                <button className="mini ghost" onClick={() => setStatus(b, "skipped")}>
                  Skip
                </button>
              )}
              {(b.status === "done" || b.status === "skipped") && (
                <span className="muted">{b.status}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
