"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createBusyBlock,
  deleteBusyBlock,
  getAvailability,
  listBusyBlocks,
  putAvailability,
  type AvailabilityRule,
  type BusyBlock,
} from "@/lib/api";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function AvailabilityPage() {
  const [rules, setRules] = useState<AvailabilityRule[] | null>(null);
  const [busy, setBusy] = useState<BusyBlock[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // new-rule / new-busy form state
  const [nr, setNr] = useState({ category: "work", weekday: 0, start_t: "10:00", end_t: "19:00" });
  const [nb, setNb] = useState({ label: "", weekday: "0", start_t: "20:00", end_t: "21:00" });

  const refresh = useCallback(async () => {
    try {
      const [r, b] = await Promise.all([getAvailability(), listBusyBlocks()]);
      setRules(r);
      setBusy(b);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function removeRule(idx: number) {
    if (!rules) return;
    setSaving(true);
    try {
      setRules(await putAvailability(rules.filter((_, i) => i !== idx)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function addRule(e: React.FormEvent) {
    e.preventDefault();
    if (!rules) return;
    setSaving(true);
    try {
      setRules(
        await putAvailability([
          ...rules,
          {
            category: nr.category as "work" | "personal",
            weekday: Number(nr.weekday),
            start_t: nr.start_t,
            end_t: nr.end_t,
          },
        ])
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function addBusy(e: React.FormEvent) {
    e.preventDefault();
    if (!nb.label.trim()) return;
    try {
      await createBusyBlock({
        label: nb.label.trim(),
        weekday: Number(nb.weekday),
        date: null,
        start_t: nb.start_t,
        end_t: nb.end_t,
      });
      setNb({ ...nb, label: "" });
      refresh();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Availability</h1>
        <span className="muted">The planner only ever schedules inside these windows</span>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <h2 className="list-title">Weekly windows</h2>
      {rules && (
        <div className="task-table-wrap">
          <table className="task-table">
            <thead>
              <tr>
                <th>Day</th>
                <th>Window</th>
                <th>Category</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r, i) => (
                <tr key={r.id}>
                  <td>{DAYS[r.weekday]}</td>
                  <td>
                    {r.start_t.slice(0, 5)}–{r.end_t.slice(0, 5)}
                  </td>
                  <td>
                    <span className={`assign-badge ${r.category === "work" ? "mine" : "maybe"}`}>
                      {r.category}
                    </span>
                  </td>
                  <td>
                    <button className="ghost-danger" disabled={saving} onClick={() => removeRule(i)}>
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form className="upload-card" onSubmit={addRule} style={{ marginTop: "0.8rem" }}>
        <select value={nr.category} onChange={(e) => setNr({ ...nr, category: e.target.value })} className="cell-input">
          <option value="work">work</option>
          <option value="personal">personal</option>
        </select>
        <select value={nr.weekday} onChange={(e) => setNr({ ...nr, weekday: Number(e.target.value) })} className="cell-input">
          {DAYS.map((d, i) => (
            <option key={d} value={i}>
              {d}
            </option>
          ))}
        </select>
        <input type="time" value={nr.start_t} onChange={(e) => setNr({ ...nr, start_t: e.target.value })} className="cell-input" />
        <input type="time" value={nr.end_t} onChange={(e) => setNr({ ...nr, end_t: e.target.value })} className="cell-input" />
        <button type="submit" disabled={saving}>
          Add window
        </button>
      </form>

      <h2 className="list-title">Busy blocks (recurring)</h2>
      {busy && busy.length === 0 && <div className="muted">None yet — e.g. gym, standups, classes.</div>}
      {busy && busy.length > 0 && (
        <div className="task-table-wrap">
          <table className="task-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>When</th>
                <th>Source</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {busy.map((b) => (
                <tr key={b.id}>
                  <td>{b.label}</td>
                  <td>
                    {b.weekday != null ? DAYS[b.weekday] : b.date} {b.start_t.slice(0, 5)}–{b.end_t.slice(0, 5)}
                  </td>
                  <td className="muted">{b.source}</td>
                  <td>
                    <button
                      className="ghost-danger"
                      onClick={async () => {
                        await deleteBusyBlock(b.id);
                        refresh();
                      }}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form className="upload-card" onSubmit={addBusy} style={{ marginTop: "0.8rem" }}>
        <input
          type="text"
          placeholder="Label (e.g. Gym)"
          value={nb.label}
          onChange={(e) => setNb({ ...nb, label: e.target.value })}
        />
        <select value={nb.weekday} onChange={(e) => setNb({ ...nb, weekday: e.target.value })} className="cell-input">
          {DAYS.map((d, i) => (
            <option key={d} value={i}>
              {d}
            </option>
          ))}
        </select>
        <input type="time" value={nb.start_t} onChange={(e) => setNb({ ...nb, start_t: e.target.value })} className="cell-input" />
        <input type="time" value={nb.end_t} onChange={(e) => setNb({ ...nb, end_t: e.target.value })} className="cell-input" />
        <button type="submit" disabled={!nb.label.trim()}>
          Add busy block
        </button>
      </form>
    </>
  );
}
