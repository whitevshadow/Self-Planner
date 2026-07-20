"use client";

import { useCallback, useEffect, useState } from "react";
import {
  carryOverBlock,
  extendBlock,
  formatTimeHM,
  getNow,
  patchBlock,
  type NowBlock,
  type NowView,
} from "@/lib/api";

/** Live "now / next" strip at the top of the Today column. Deterministic —
 * reads GET /plan/now and drives the active block's quick actions. */
export default function NowCard({
  version,
  onChanged,
}: {
  version: number;
  onChanged: () => void;
}) {
  const [view, setView] = useState<NowView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setView(await getNow());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    }
  }, []);

  // Refetch on mount, when the parent replans (version bump), and every minute
  // so "right now" stays honest without a reload.
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 60_000);
    return () => clearInterval(t);
  }, [refresh, version]);

  async function act(fn: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await fn();
      await refresh();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  if (view === null) return null;

  const { current, next, free_minutes } = view;

  const nextLabel = (b: NowBlock) => {
    const start = new Date(b.start_at);
    const isToday = start.toDateString() === new Date().toDateString();
    const day = isToday
      ? ""
      : `${start.toLocaleDateString(undefined, { weekday: "short" })} `;
    return `${day}${formatTimeHM(b.start_at)}`;
  };

  return (
    <div className={`now-card ${current ? "active" : "idle"}`}>
      {current ? (
        <>
          <div className="now-head">
            <span className="now-dot" />
            Right now
            <span className="now-time">
              until {formatTimeHM(current.end_at)}
            </span>
          </div>
          <div className="now-title">{current.task_title}</div>
          <div className="now-actions">
            <button className="mini" disabled={busy} onClick={() => act(() => patchBlock(current.id, { status: "done" }))}>
              ✓ Done
            </button>
            <button className="mini ghost" disabled={busy} onClick={() => act(() => extendBlock(current.id, 15))}>
              +15 min
            </button>
            <button className="mini ghost" disabled={busy} onClick={() => act(() => carryOverBlock(current.id))}>
              Carry over
            </button>
          </div>
          {next && <div className="now-next">Next: {next.task_title} · {nextLabel(next)}</div>}
        </>
      ) : next ? (
        <>
          <div className="now-head">
            <span className="now-dot idle" />
            {free_minutes != null && free_minutes > 0
              ? `Free for ${free_minutes} min`
              : "Up next"}
          </div>
          <div className="now-title">{next.task_title}</div>
          <div className="now-next">Starts {nextLabel(next)}</div>
        </>
      ) : (
        <div className="now-head">
          <span className="now-dot idle" />
          Nothing scheduled right now
        </div>
      )}
      {error && <div className="now-error">{error}</div>}
    </div>
  );
}
