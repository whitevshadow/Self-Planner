"use client";

import { useCallback, useEffect, useState } from "react";
import NowCard from "@/components/NowCard";
import {
  formatTimeHM,
  patchBlock,
  planToday,
  replanToday,
  runPlan,
  type DayBlock,
  type PlanWarning,
} from "@/lib/api";

export default function TodayColumn() {
  const [blocks, setBlocks] = useState<DayBlock[] | null>(null);
  const [warnings, setWarnings] = useState<PlanWarning[]>([]);
  const [planning, setPlanning] = useState<null | "full" | "today">(null);
  const [error, setError] = useState<string | null>(null);
  const [nowVersion, setNowVersion] = useState(0);

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

  async function plan(mode: "full" | "today") {
    setPlanning(mode);
    setError(null);
    try {
      const r = mode === "full" ? await runPlan() : await replanToday();
      setBlocks(r.today);
      setWarnings(r.warnings);
      setNowVersion((v) => v + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Planning failed");
    } finally {
      setPlanning(null);
    }
  }

  async function setStatus(b: DayBlock, status: DayBlock["status"]) {
    await patchBlock(b.id, { status });
    setNowVersion((v) => v + 1);
    refresh();
  }

  return (
    <div className="today-col">
      <div className="section-header" style={{ margin: "0 0 0.6rem" }}>
        <h2>Today</h2>
        <div className="today-actions">
          <button className="ghost" onClick={() => plan("today")} disabled={planning !== null}>
            {planning === "today" ? "Replanning…" : "Replan today"}
          </button>
          <button onClick={() => plan("full")} disabled={planning !== null}>
            {planning === "full" ? "Planning…" : "Full replan"}
          </button>
        </div>
      </div>

      <NowCard
        version={nowVersion}
        onChanged={() => {
          setNowVersion((v) => v + 1);
          refresh();
        }}
      />

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
            <div className="block-title" title={b.task_title}>
              {b.task_title}
              {b.pinned && <span title="Pinned — replans won't move it"> 📌</span>}
              {b.at_risk && <span className="prio high" style={{ marginLeft: "0.4rem" }}>at risk</span>}
            </div>
            <div className="block-foot">
              <span className="block-time">
                {formatTimeHM(b.start_at)}–{formatTimeHM(b.end_at)}
              </span>
              <span className="block-meta">
                {b.category}
                {b.priority ? ` · ${b.priority}` : ""}
              </span>
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
          </div>
        ))}
      </div>
    </div>
  );
}
