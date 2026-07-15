"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  confirmTimetable,
  getChatHistory,
  parseTimetable,
  sendChat,
  type ChatMessage,
  type TimetableEntry,
} from "@/lib/api";

const DAY_LABEL: Record<string, string> = {
  mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun",
};

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<TimetableEntry[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

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
  }, [messages, preview]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
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

  return (
    <>
      <div className="page-header">
        <h1>Chat</h1>
        <span className="muted">Add tasks, ask about your schedule, or upload a timetable</span>
      </div>

      <div className="chat-box">
        <div className="chat-scroll">
          {messages.length === 0 && !error && (
            <div className="empty">
              Try: &quot;remind me to review Rahul&apos;s PR by Thursday&quot; · &quot;what&apos;s my day look
              like?&quot; · &quot;mark the signup form task done&quot; — or drop a timetable file below.
            </div>
          )}
          {messages.map((m) =>
            m.role === "tool" ? (
              <div className="chat-tool" key={m.id} title={m.content}>
                ⚙ {m.tool_calls?.[0]?.tool ?? "tool"} executed
              </div>
            ) : (
              <div className={`chat-msg ${m.role}`} key={m.id}>
                {m.content.split("\n").map((line, i) => (
                  <div key={i}>{line}</div>
                ))}
              </div>
            )
          )}
          {busy && (
            <div className="chat-msg assistant">
              <span className="spinner" />
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

        <form className="chat-input" onSubmit={submit}>
          <button
            type="button"
            className="mini ghost"
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
          <input
            type="text"
            placeholder="Ask or instruct… (e.g. 'add task: prepare demo, work, by Friday')"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
          />
          <button type="submit" disabled={busy || !input.trim()}>
            Send
          </button>
        </form>
      </div>
    </>
  );
}
