"use client";

import { useEffect, useRef, useState } from "react";
import {
  formatTimestamp,
  listPeople,
  setSegmentSpeaker,
  type MeetingDetail,
  type Person,
  type Segment,
} from "@/lib/api";

const SPEAKER_COLORS = ["#5b8def", "#4cbf7a", "#d9a441", "#c678dd", "#56b6c2", "#e5636c"];

export default function TranscriptView({
  meeting,
  highlightIdxs,
  flashIdx,
  manualLabeling = false,
  onChanged,
}: {
  meeting: MeetingDetail;
  highlightIdxs?: Set<number>;
  flashIdx?: number | null;
  manualLabeling?: boolean;
  onChanged?: (m: MeetingDetail) => void;
}) {
  const segments = meeting.segments;
  const [people, setPeople] = useState<Person[]>([]);
  const flashRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (manualLabeling) listPeople().then(setPeople).catch(() => {});
  }, [manualLabeling]);

  useEffect(() => {
    if (flashIdx != null && flashRef.current) {
      flashRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [flashIdx]);

  if (segments.length === 0) return <div className="empty">No transcript segments.</div>;

  const colorFor = (s: Segment): string | undefined => {
    const key = s.speaker ?? s.speaker_raw;
    if (!key) return undefined;
    const keys = [...new Set(segments.map((x) => x.speaker ?? x.speaker_raw).filter(Boolean))];
    return SPEAKER_COLORS[keys.indexOf(key) % SPEAKER_COLORS.length];
  };

  async function label(idx: number, speaker: string) {
    const updated = await setSegmentSpeaker(meeting.id, idx, speaker);
    onChanged?.(updated);
  }

  return (
    <div className="transcript">
      {segments.map((s) => {
        const speakerName = s.speaker ?? s.speaker_raw?.replace("SPEAKER_", "Speaker ");
        const highlighted = highlightIdxs?.has(s.idx);
        const flashing = flashIdx === s.idx;
        return (
          <div
            className={`segment ${highlighted ? "hl" : ""} ${flashing ? "flash" : ""}`}
            key={s.idx}
            ref={flashing ? flashRef : undefined}
          >
            <span className="ts">[{formatTimestamp(s.start_sec)}]</span>
            <span className="text">
              {speakerName && (
                <strong style={{ color: colorFor(s) }}>{speakerName}: </strong>
              )}
              {s.text}
            </span>
            {manualLabeling && (
              <select
                className="cell-input seg-speaker"
                value={s.speaker ?? ""}
                onChange={(e) => label(s.idx, e.target.value)}
              >
                <option value="">—</option>
                {people.map((p) => (
                  <option key={p.id} value={p.name}>
                    {p.name}
                  </option>
                ))}
              </select>
            )}
          </div>
        );
      })}
    </div>
  );
}
