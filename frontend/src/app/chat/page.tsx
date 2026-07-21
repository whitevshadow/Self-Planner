"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  clearChat,
  confirmTimetable,
  getChatHistory,
  parseTimetable,
  sendChat,
  speakText,
  transcribeAudio,
  voiceEnabled,
  type ChatMessage,
  type TimetableEntry,
} from "@/lib/api";

const DAY_LABEL: Record<string, string> = {
  mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun",
};

const SUGGESTIONS = [
  "What does my day look like?",
  "Remind me to review Rahul's PR by Thursday",
  "Add task: prepare demo, work, high priority, by Friday",
  "Mark the signup form task done",
];

/** Friendlier label for a tool-call chip than the raw tool name. */
function toolLabel(tool: string | undefined): string {
  switch (tool) {
    case "add_task":
      return "Task added";
    case "add_tasks":
      return "Tasks added";
    case "update_task":
      return "Task updated";
    case "replan":
      return "Schedule replanned";
    case "query":
      return "Checked your schedule";
    default:
      return `${tool ?? "tool"} executed`;
  }
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<TimetableEntry[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  // --- Live voice: record → gateway STT → agent → gateway TTS → play ---
  const [recording, setRecording] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [ttsOn, setTtsOn] = useState(false); // server has spoken replies enabled
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);

  useEffect(() => {
    voiceEnabled().then(setTtsOn).catch(() => setTtsOn(false));
  }, []);

  const stopPlayback = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    setSpeaking(false);
  }, []);

  const speak = useCallback(
    async (text: string) => {
      if (!ttsOn || !text.trim()) return;
      try {
        const url = await speakText(text);
        if (!url) return;
        stopPlayback();
        audioUrlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        audio.onended = stopPlayback;
        setSpeaking(true);
        await audio.play();
      } catch {
        stopPlayback();
      }
    },
    [ttsOn, stopPlayback]
  );

  const processUtterance = useCallback(
    async (blob: Blob) => {
      setBusy(true);
      try {
        const text = (await transcribeAudio(blob)).trim();
        if (!text) return;
        setMessages((m) => [
          ...m,
          { id: "tmp", role: "user", content: text, tool_calls: null, created_at: new Date().toISOString() },
        ]);
        const created = await sendChat(text);
        await getChatHistory().then(setMessages).catch(() => {});
        const reply = [...created].reverse().find((m) => m.role === "assistant");
        if (reply) await speak(reply.content);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Voice message failed");
      } finally {
        setBusy(false);
      }
    },
    [speak]
  );

  const toggleMic = useCallback(async () => {
    // Tap while the assistant is speaking = barge-in: cut the reply and listen.
    if (speaking) stopPlayback();
    if (recording) {
      recorderRef.current?.stop(); // fires onstop → processUtterance
      return;
    }
    if (busy) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => e.data.size > 0 && chunksRef.current.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        if (blob.size > 0) processUtterance(blob);
      };
      recorderRef.current = rec;
      rec.start();
      setRecording(true);
      setError(null);
    } catch {
      setError("Microphone access was denied.");
    }
  }, [recording, speaking, busy, stopPlayback, processUtterance]);

  useEffect(() => stopPlayback, [stopPlayback]); // stop audio on unmount

  const refresh = useCallback(async () => {
    try {
      setMessages(await getChatHistory());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load chat");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, preview, busy]);

  // Auto-grow the composer up to a max height (ChatGPT-style).
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [input]);

  const send = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      if (!text || busy) return;
      setInput("");
      setBusy(true);
      setMessages((m) => [
        ...m,
        { id: "tmp", role: "user", content: text, tool_calls: null, created_at: new Date().toISOString() },
      ]);
      try {
        await sendChat(text);
        await refresh();
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Send failed");
      } finally {
        setBusy(false);
      }
    },
    [busy, refresh]
  );

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  }

  async function newChat() {
    if (busy) return;
    if (messages.length > 0 && !confirm("Start a new chat? This clears the current conversation.")) return;
    setBusy(true);
    try {
      await clearChat();
      setMessages([]);
      setPreview(null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't start a new chat");
    } finally {
      setBusy(false);
    }
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      setPreview(await parseTimetable(file));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Timetable parsing failed");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function confirmEntries() {
    if (!preview) return;
    setConfirming(true);
    try {
      const r = await confirmTimetable(preview);
      setPreview(null);
      setMessages((m) => [
        ...m,
        {
          id: `tt-${Date.now()}`,
          role: "assistant",
          content: `Saved ${r.created} recurring busy block(s) from your timetable. They'll be avoided in future plans.`,
          tool_calls: null,
          created_at: new Date().toISOString(),
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setConfirming(false);
    }
  }

  const empty = messages.length === 0 && !preview;

  return (
    <>
      <div className={`chat-box${empty ? " empty" : ""}`}>
        <div className="chat-topbar">
          <span className="chat-topbar-title">Chat</span>
          <span className="muted">Add tasks, ask about your schedule, or upload a timetable</span>
          <button className="mini ghost new-chat-btn" onClick={newChat} disabled={busy}>
            ＋ New chat
          </button>
        </div>
        <div className="chat-scroll">
          {empty && !error && (
            <div className="chat-welcome">
              <div className="chat-welcome-avatar">S</div>
              <h2>How can I help you plan?</h2>
              <p className="muted">Ask about your schedule, add tasks in plain English, or drop a timetable below.</p>
              <div className="chat-suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chat-suggestion" onClick={() => send(s)} disabled={busy}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) =>
            m.role === "tool" ? (
              <div className="chat-tool" key={m.id} title={m.content}>
                <span className="chat-tool-check">✓</span> {toolLabel(m.tool_calls?.[0]?.tool)}
              </div>
            ) : (
              <div className={`chat-row ${m.role}`} key={m.id}>
                {m.role === "assistant" && <div className="chat-avatar">S</div>}
                <div className={`chat-msg ${m.role}`}>
                  {m.content.split("\n").map((line, i) => (
                    <div key={i}>{line || " "}</div>
                  ))}
                </div>
              </div>
            )
          )}

          {busy && (
            <div className="chat-row assistant">
              <div className="chat-avatar">S</div>
              <div className="chat-msg assistant typing">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
              </div>
            </div>
          )}

          {preview && (
            <div className="tt-preview">
              <h3>Timetable preview — confirm to save as busy blocks</h3>
              {preview.length === 0 && <div className="muted">Nothing recognized as a timetable.</div>}
              {preview.length > 0 && (
                <table className="task-table">
                  <thead>
                    <tr>
                      <th>Day</th>
                      <th>Time</th>
                      <th>Activity</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.map((e, i) => (
                      <tr key={i}>
                        <td>{DAY_LABEL[e.day]}</td>
                        <td>
                          {e.start}–{e.end}
                        </td>
                        <td>{e.label}</td>
                        <td>
                          <button
                            className="ghost-danger"
                            onClick={() => setPreview(preview.filter((_, j) => j !== i))}
                          >
                            ✕
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className="speaker-actions">
                <button onClick={confirmEntries} disabled={confirming || preview.length === 0}>
                  {confirming ? "Saving…" : `Confirm ${preview.length} block(s)`}
                </button>
                <button className="mini ghost" onClick={() => setPreview(null)}>
                  Discard
                </button>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {error && <div className="error-banner">{error}</div>}

        <form
          className="chat-input"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <button
            type="button"
            className="chat-attach"
            title="Upload timetable (image, PDF, CSV, Excel, txt)"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
          >
            📎
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".png,.jpg,.jpeg,.webp,.pdf,.csv,.xlsx,.xls,.txt"
            style={{ display: "none" }}
            onChange={onFile}
          />
          <textarea
            ref={taRef}
            rows={1}
            placeholder="Ask or instruct…  (e.g. 'add task: prepare demo, work, by Friday')"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={busy}
          />
          <button
            type="button"
            className={`chat-mic${recording ? " recording" : ""}${speaking ? " speaking" : ""}`}
            onClick={toggleMic}
            disabled={busy && !recording && !speaking}
            title={
              speaking ? "Stop speaking" : recording ? "Stop & send" : "Talk to the assistant"
            }
          >
            {speaking ? "⏹" : recording ? "●" : "🎤"}
          </button>
          <button type="submit" className="chat-send" disabled={busy || !input.trim()} title="Send">
            ↑
          </button>
        </form>
      </div>
    </>
  );
}
