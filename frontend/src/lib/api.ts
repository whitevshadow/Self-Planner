const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api";

export interface Segment {
  idx: number;
  start_sec: number;
  end_sec: number;
  text: string;
  speaker: string | null;
  speaker_raw: string | null;
}

export interface Person {
  id: string;
  name: string;
  aliases: string[];
  is_me: boolean;
}

export interface Meeting {
  id: string;
  title: string;
  filename: string;
  status: "uploaded" | "transcribing" | "done" | "failed";
  duration_sec: number | null;
  error: string | null;
  has_audio: boolean;
  created_at: string;
}

/** Range-streamed audio URL for a meeting's <audio> element. */
export function audioUrl(meetingId: string): string {
  return `${API_BASE}/meetings/${meetingId}/audio`;
}

/** Full-data backup zip (meetings, tasks, plan, settings + per-meeting Markdown). */
export function exportUrl(): string {
  return `${API_BASE}/export`;
}

export interface Task {
  id: string;
  meeting_id: string;
  title: string;
  owner: string | null;
  due_date: string | null;
  start_date: string | null;
  priority: "high" | "medium" | "low" | null;
  dependencies: string[];
  source_quote: string | null;
  status: "open" | "done" | "dropped";
  edited: boolean;
  assignment: "mine" | "maybe" | "others";
  assignment_reason: string | null;
  assignment_source: "llm" | "user";
  segment_idx: number | null;
  category: "work" | "personal";
  estimated_minutes: number | null;
  estimate_source: string;
  intensity: "heavy" | "light" | null;
  steps: string[];
  progress: number;
  at_risk: boolean;
  created_at: string;
}

export interface MeetingDetail extends Meeting {
  summary: string | null;
  decisions: string[] | null;
  notes: string | null;
  extract_status: "pending" | "running" | "done" | "failed";
  extract_error: string | null;
  extract_progress: { stage: "summary" | "extract" | "notes"; done: number; total: number } | null;
  diarize_status: "pending" | "running" | "done" | "failed" | "skipped";
  speaker_map: Record<string, string>;
  segments: Segment[];
  tasks: Task[];
}

/** True while any background pipeline stage may still change the meeting. */
export function isProcessing(m: MeetingDetail | Meeting): boolean {
  if (m.status === "transcribing" || m.status === "uploaded") return true;
  if ("extract_status" in m) {
    const d = m as MeetingDetail;
    if (d.status === "done" && (d.extract_status === "pending" || d.extract_status === "running")) return true;
    if (d.diarize_status === "running") return true;
  }
  return false;
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export async function listMeetings(): Promise<Meeting[]> {
  return handle(await fetch(`${API_BASE}/meetings`, { cache: "no-store" }));
}

export async function getMeeting(id: string): Promise<MeetingDetail> {
  return handle(await fetch(`${API_BASE}/meetings/${id}`, { cache: "no-store" }));
}

export async function uploadMeeting(file: File, title?: string): Promise<MeetingDetail> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  // Transcription is synchronous — allow up to 10 minutes.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10 * 60 * 1000);
  try {
    return await handle(
      await fetch(`${API_BASE}/meetings`, { method: "POST", body: form, signal: controller.signal })
    );
  } finally {
    clearTimeout(timer);
  }
}

export async function createMeetingFromText(text: string, title?: string): Promise<MeetingDetail> {
  // Returns 202 immediately; extraction runs in the background — poll getMeeting.
  return handle(
    await fetch(`${API_BASE}/meetings/text`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, title: title || null }),
    })
  );
}

export async function deleteMeeting(id: string): Promise<void> {
  return handle(await fetch(`${API_BASE}/meetings/${id}`, { method: "DELETE" }));
}

export async function reTranscribe(meetingId: string): Promise<MeetingDetail> {
  // Returns 202 immediately; the full pipeline re-runs — poll getMeeting for status.
  return handle(await fetch(`${API_BASE}/meetings/${meetingId}/retranscribe`, { method: "POST" }));
}

export async function reExtract(meetingId: string): Promise<MeetingDetail> {
  // Returns 202 immediately; poll getMeeting for extract_status/extract_progress.
  return handle(await fetch(`${API_BASE}/meetings/${meetingId}/extract`, { method: "POST" }));
}

export async function listTasks(filters?: {
  owner?: string;
  status?: string;
  assignment?: string;
}): Promise<Task[]> {
  const params = new URLSearchParams();
  if (filters?.owner) params.set("owner", filters.owner);
  if (filters?.status) params.set("status", filters.status);
  if (filters?.assignment) params.set("assignment", filters.assignment);
  const qs = params.toString();
  return handle(await fetch(`${API_BASE}/tasks${qs ? `?${qs}` : ""}`, { cache: "no-store" }));
}

/** Take ownership of tasks ticked on the meeting page. The server also triages
 * them (priority, duration, start date, deadline), so this can take a few seconds. */
export async function assignTasksToMe(taskIds: string[]): Promise<Task[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 2 * 60 * 1000);
  try {
    return await handle(
      await fetch(`${API_BASE}/tasks/assign-mine`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_ids: taskIds }),
        signal: controller.signal,
      })
    );
  } finally {
    clearTimeout(timer);
  }
}

export async function confirmTask(id: string): Promise<Task> {
  return handle(await fetch(`${API_BASE}/tasks/${id}/confirm`, { method: "POST" }));
}

export async function dismissTask(id: string): Promise<Task> {
  return handle(await fetch(`${API_BASE}/tasks/${id}/dismiss`, { method: "POST" }));
}

export async function saveSpeakerMap(
  meetingId: string,
  mapping: Record<string, string>
): Promise<MeetingDetail> {
  return handle(
    await fetch(`${API_BASE}/meetings/${meetingId}/speaker-map`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(mapping),
    })
  );
}

export async function setSegmentSpeaker(
  meetingId: string,
  segmentIdx: number,
  speaker: string
): Promise<MeetingDetail> {
  return handle(
    await fetch(`${API_BASE}/meetings/${meetingId}/segments/${segmentIdx}/speaker`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ speaker }),
    })
  );
}

export async function listPeople(): Promise<Person[]> {
  return handle(await fetch(`${API_BASE}/people`, { cache: "no-store" }));
}

export async function createPerson(p: Omit<Person, "id">): Promise<Person> {
  return handle(
    await fetch(`${API_BASE}/people`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    })
  );
}

export async function updatePerson(id: string, p: Omit<Person, "id">): Promise<Person> {
  return handle(
    await fetch(`${API_BASE}/people/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    })
  );
}

export async function deletePerson(id: string): Promise<void> {
  return handle(await fetch(`${API_BASE}/people/${id}`, { method: "DELETE" }));
}

// --- Phase 4: planner ---

export interface AvailabilityRule {
  id: string;
  category: "work" | "personal";
  weekday: number; // 0=Mon … 6=Sun
  start_t: string; // "10:00:00"
  end_t: string;
  energy: "deep" | "shallow";
}

export interface BusyBlock {
  id: string;
  label: string;
  weekday: number | null;
  date: string | null;
  start_t: string;
  end_t: string;
  source: string;
}

export interface DayBlock {
  id: string;
  task_id: string;
  task_title: string;
  category: string;
  priority: string | null;
  start_at: string;
  end_at: string;
  status: "planned" | "in_progress" | "done" | "skipped";
  pinned: boolean;
  at_risk: boolean;
}

export interface PlanWarning {
  task_id: string;
  title: string;
  kind: string;
  detail: string;
}

export interface PlanResponse {
  warnings: PlanWarning[];
  today: DayBlock[];
}

export async function getAvailability(): Promise<AvailabilityRule[]> {
  return handle(await fetch(`${API_BASE}/availability`, { cache: "no-store" }));
}

export async function putAvailability(rules: Omit<AvailabilityRule, "id">[]): Promise<AvailabilityRule[]> {
  return handle(
    await fetch(`${API_BASE}/availability`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rules),
    })
  );
}

export async function listBusyBlocks(): Promise<BusyBlock[]> {
  return handle(await fetch(`${API_BASE}/busy-blocks`, { cache: "no-store" }));
}

export async function createBusyBlock(b: Omit<BusyBlock, "id" | "source">): Promise<BusyBlock> {
  return handle(
    await fetch(`${API_BASE}/busy-blocks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b),
    })
  );
}

export async function deleteBusyBlock(id: string): Promise<void> {
  return handle(await fetch(`${API_BASE}/busy-blocks/${id}`, { method: "DELETE" }));
}

export async function runPlan(): Promise<PlanResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5 * 60 * 1000);
  try {
    return await handle(
      await fetch(`${API_BASE}/plan`, { method: "POST", signal: controller.signal })
    );
  } finally {
    clearTimeout(timer);
  }
}

export async function planToday(): Promise<DayBlock[]> {
  return handle(await fetch(`${API_BASE}/plan/today`, { cache: "no-store" }));
}

export interface NowBlock {
  id: string;
  task_id: string;
  task_title: string;
  category: string;
  priority: string | null;
  start_at: string;
  end_at: string;
  status: "planned" | "in_progress" | "done" | "skipped";
}

export interface NowView {
  now: string;
  current: NowBlock | null;
  next: NowBlock | null;
  free_minutes: number | null;
}

export async function getNow(): Promise<NowView> {
  return handle(await fetch(`${API_BASE}/plan/now`, { cache: "no-store" }));
}

/** Deterministic repack from now — no triage, returns immediately. */
export async function replanToday(): Promise<PlanResponse> {
  return handle(await fetch(`${API_BASE}/plan/replan`, { method: "POST" }));
}

export async function extendBlock(id: string, minutes = 15): Promise<PlanResponse> {
  return handle(
    await fetch(`${API_BASE}/schedule-blocks/${id}/extend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ minutes }),
    })
  );
}

export async function carryOverBlock(id: string): Promise<PlanResponse> {
  return handle(await fetch(`${API_BASE}/schedule-blocks/${id}/carry-over`, { method: "POST" }));
}

export async function patchBlock(
  id: string,
  patch: { status?: DayBlock["status"]; start_at?: string; end_at?: string }
): Promise<void> {
  return handle(
    await fetch(`${API_BASE}/schedule-blocks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    })
  );
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  tool_calls: { tool: string; args: Record<string, unknown> }[] | null;
  created_at: string;
}

export interface TimetableEntry {
  day: "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
  start: string;
  end: string;
  label: string;
}

export async function getChatHistory(): Promise<ChatMessage[]> {
  return handle(await fetch(`${API_BASE}/chat`, { cache: "no-store" }));
}

export async function sendChat(message: string): Promise<ChatMessage[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5 * 60 * 1000);
  try {
    return await handle(
      await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
        signal: controller.signal,
      })
    );
  } finally {
    clearTimeout(timer);
  }
}

export async function clearChat(): Promise<void> {
  return handle(await fetch(`${API_BASE}/chat`, { method: "DELETE" }));
}

// --- Voice: STT + TTS through the gateway (localhost:1050) ---

/** True when the backend has spoken replies enabled (TTS_PROVIDER != off). */
export async function voiceEnabled(): Promise<boolean> {
  try {
    const r = await handle<{ tts_enabled: boolean }>(
      await fetch(`${API_BASE}/voice/config`, { cache: "no-store" })
    );
    return r.tts_enabled;
  } catch {
    return false;
  }
}

/** Send one recorded utterance to the gateway ASR and get back the transcript. */
export async function transcribeAudio(blob: Blob): Promise<string> {
  const form = new FormData();
  const ext = blob.type.includes("ogg") ? "ogg" : blob.type.includes("mp4") ? "mp4" : "webm";
  form.append("audio", blob, `speech.${ext}`);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60 * 1000);
  try {
    const r = await handle<{ text: string }>(
      await fetch(`${API_BASE}/voice/transcribe`, { method: "POST", body: form, signal: controller.signal })
    );
    return r.text;
  } finally {
    clearTimeout(timer);
  }
}

/** Synthesize reply text to speech; returns an object URL for an <audio> element
 * (caller must URL.revokeObjectURL it when done). null if TTS is disabled. */
export async function speakText(text: string): Promise<string | null> {
  const res = await fetch(`${API_BASE}/voice/speak`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (res.status === 409) return null; // voice replies disabled server-side
  if (!res.ok) throw new Error(`Speech failed (${res.status})`);
  return URL.createObjectURL(await res.blob());
}

export async function parseTimetable(file: File): Promise<TimetableEntry[]> {
  const form = new FormData();
  form.append("file", file);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5 * 60 * 1000);
  try {
    return await handle(
      await fetch(`${API_BASE}/timetable/parse`, { method: "POST", body: form, signal: controller.signal })
    );
  } finally {
    clearTimeout(timer);
  }
}

export async function confirmTimetable(entries: TimetableEntry[]): Promise<{ created: number }> {
  return handle(
    await fetch(`${API_BASE}/timetable/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(entries),
    })
  );
}

export function formatTimeHM(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export async function updateTask(id: string, patch: Partial<Task>): Promise<Task> {
  return handle(
    await fetch(`${API_BASE}/tasks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    })
  );
}

export async function deleteTask(id: string): Promise<void> {
  return handle(await fetch(`${API_BASE}/tasks/${id}`, { method: "DELETE" }));
}

export function formatTimestamp(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** Task effort estimate as "45m" / "2h" / "1h 30m". */
export function formatMinutes(min: number | null): string {
  if (min == null) return "—";
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (!h) return `${m}m`;
  return m ? `${h}h ${m}m` : `${h}h`;
}

export function formatDuration(sec: number | null): string {
  if (sec == null) return "—";
  const m = Math.round(sec / 60);
  return m < 1 ? "<1 min" : `${m} min`;
}
