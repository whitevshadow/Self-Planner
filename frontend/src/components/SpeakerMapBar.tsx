"use client";

import { useEffect, useMemo, useState } from "react";
import {
  createPerson,
  listPeople,
  saveSpeakerMap,
  type MeetingDetail,
  type Person,
} from "@/lib/api";

/** Rename raw diarization labels (SPEAKER_00…) to real people from the registry. */
export default function SpeakerMapBar({
  meeting,
  onSaved,
}: {
  meeting: MeetingDetail;
  onSaved: (m: MeetingDetail) => void;
}) {
  const [people, setPeople] = useState<Person[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>(meeting.speaker_map);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPeople().then(setPeople).catch(() => {});
  }, []);

  const rawLabels = useMemo(() => {
    const labels = new Map<string, string>(); // label -> sample quote
    for (const s of meeting.segments) {
      if (s.speaker_raw && !labels.has(s.speaker_raw)) labels.set(s.speaker_raw, s.text);
    }
    return [...labels.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [meeting.segments]);

  if (rawLabels.length === 0) return null;

  async function handleSelect(label: string, value: string) {
    if (value === "__new__") {
      const name = prompt("New person's name:");
      if (!name?.trim()) return;
      try {
        const p = await createPerson({ name: name.trim(), aliases: [], is_me: false });
        setPeople((prev) => [...prev, p]);
        setMapping((prev) => ({ ...prev, [label]: p.name }));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to add person");
      }
    } else {
      setMapping((prev) => ({ ...prev, [label]: value }));
    }
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const cleaned = Object.fromEntries(Object.entries(mapping).filter(([, v]) => v));
      onSaved(await saveSpeakerMap(meeting.id, cleaned));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  const dirty = JSON.stringify(mapping) !== JSON.stringify(meeting.speaker_map);

  return (
    <div className="speaker-bar">
      <h3>Speakers detected — who is who?</h3>
      <div className="speaker-rows">
        {rawLabels.map(([label, quote]) => (
          <div className="speaker-row" key={label}>
            <span className={`speaker-chip ${label.toLowerCase()}`}>{label.replace("SPEAKER_", "Speaker ")}</span>
            <span className="sample" title={quote}>
              “{quote.length > 70 ? quote.slice(0, 70) + "…" : quote}”
            </span>
            <select
              className="cell-input"
              value={mapping[label] ?? ""}
              onChange={(e) => handleSelect(label, e.target.value)}
            >
              <option value="">— unmapped —</option>
              {people.map((p) => (
                <option key={p.id} value={p.name}>
                  {p.name}
                  {p.is_me ? " (me)" : ""}
                </option>
              ))}
              <option value="__new__">+ add new person…</option>
            </select>
          </div>
        ))}
      </div>
      <div className="speaker-actions">
        <button onClick={save} disabled={busy || !dirty}>
          {busy ? "Saving + reclassifying…" : "Save mapping"}
        </button>
        {error && <span className="overdue-text">{error}</span>}
      </div>
    </div>
  );
}
