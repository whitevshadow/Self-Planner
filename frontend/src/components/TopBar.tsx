"use client";

import { useRouter, usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { listMeetings, listTasks, type Meeting, type Task } from "@/lib/api";

const TITLES: [string, string][] = [
  ["/meetings", "Meetings"],
  ["/tasks", "My Tasks"],
  ["/chat", "Chat"],
  ["/gantt", "Gantt"],
  ["/settings/people", "People"],
  ["/settings/availability", "Availability"],
];

function pageTitle(pathname: string): string {
  if (pathname === "/") return "Dashboard";
  return TITLES.find(([p]) => pathname.startsWith(p))?.[1] ?? "Self Planner";
}

export default function TopBar({ onMenu }: { onMenu: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState(0);
  const [data, setData] = useState<{ tasks: Task[]; meetings: Meeting[] } | null>(null);

  // Lazy-load the search index on first focus; refresh per page navigation.
  const load = useCallback(async () => {
    try {
      const [tasks, meetings] = await Promise.all([listTasks(), listMeetings()]);
      setData({ tasks, meetings });
    } catch {
      setData({ tasks: [], meetings: [] });
    }
  }, []);

  useEffect(() => {
    setData(null);
    setOpen(false);
    setQ("");
  }, [pathname]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
      if (e.key === "Escape") setOpen(false);
    }
    function onClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, []);

  const needle = q.trim().toLowerCase();
  const tasks = needle
    ? (data?.tasks ?? []).filter((t) => t.title.toLowerCase().includes(needle)).slice(0, 6)
    : [];
  const meetings = needle
    ? (data?.meetings ?? []).filter((m) => m.title.toLowerCase().includes(needle)).slice(0, 6)
    : [];
  const flat = [
    ...tasks.map((t) => ({ href: `/meetings/${t.meeting_id}?task=${t.id}`, key: `t${t.id}` })),
    ...meetings.map((m) => ({ href: `/meetings/${m.id}`, key: `m${m.id}` })),
  ];

  function go(href: string) {
    setOpen(false);
    setQ("");
    router.push(href);
  }

  // The bell reuses the search index — no extra request. It only has a count
  // once something has loaded that index, which is fine: it is an ambient
  // signal, not a primary control.
  const today = new Date().toISOString().slice(0, 10);
  const overdue = (data?.tasks ?? []).filter(
    (t) => t.status === "open" && t.due_date != null && t.due_date < today
  ).length;

  // Load the index once on mount so the bell is accurate before the user
  // ever opens search.
  useEffect(() => {
    if (!data) load();
  }, [data, load]);

  return (
    <header className="appbar">
      <button className="hamburger" onClick={onMenu} aria-label="Open navigation">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />
        </svg>
      </button>
      <span className="appbar-title">{pageTitle(pathname)}</span>
      <div className="appbar-spacer" />
      <div className={`search-wrap ${q ? "typing" : ""}`} ref={wrapRef}>
        <svg
          className="search-icon"
          viewBox="0 0 24 24"
          width="15"
          height="15"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" strokeLinecap="round" />
        </svg>
        <input
          ref={inputRef}
          className="search-pill"
          placeholder="Search tasks, meetings…"
          aria-label="Search tasks and meetings"
          value={q}
          onFocus={() => {
            if (!data) load();
            setOpen(true);
          }}
          onChange={(e) => {
            setQ(e.target.value);
            setSel(0);
            setOpen(true);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, flat.length - 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
            if (e.key === "Enter" && flat[sel]) go(flat[sel].href);
          }}
        />
        {open && needle.length > 0 && (
          <div className="search-pop">
            {tasks.length > 0 && <div className="search-group">Tasks</div>}
            {tasks.map((t, i) => (
              <a
                key={t.id}
                className={`search-item ${sel === i ? "sel" : ""}`}
                onClick={() => go(`/meetings/${t.meeting_id}?task=${t.id}`)}
              >
                {t.title}
                <div className="sub">{t.status} {t.due_date ? `· due ${t.due_date}` : ""}</div>
              </a>
            ))}
            {meetings.length > 0 && <div className="search-group">Meetings</div>}
            {meetings.map((m, i) => (
              <a
                key={m.id}
                className={`search-item ${sel === tasks.length + i ? "sel" : ""}`}
                onClick={() => go(`/meetings/${m.id}`)}
              >
                {m.title}
                <div className="sub">{new Date(m.created_at).toLocaleDateString()}</div>
              </a>
            ))}
            {flat.length === 0 && (
              <div className="search-empty">
                {data ? `No matches for "${q.trim()}"` : "Loading…"}
              </div>
            )}
          </div>
        )}
        <span className="search-kbd" aria-hidden>
          Ctrl K
        </span>
      </div>
      <div className="appbar-spacer" />
      <div className="appbar-right">
        <button
          className="icon-btn"
          onClick={() => router.push("/tasks")}
          aria-label={
            overdue === 0 ? "No overdue tasks" : `${overdue} overdue task${overdue === 1 ? "" : "s"}`
          }
          title={overdue === 0 ? "Nothing overdue" : `${overdue} overdue`}
        >
          <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M18 8a6 6 0 1 0-12 0c0 6-2 7-2 7h16s-2-1-2-7" strokeLinejoin="round" />
            <path d="M10.5 20a2 2 0 0 0 3 0" strokeLinecap="round" />
          </svg>
          {/* No badge at zero — a "0" is noise, not information. */}
          {overdue > 0 && <span className="count-badge">{overdue > 9 ? "9+" : overdue}</span>}
        </button>
        <div className="appbar-me">
          <div className="sb-avatar">AN</div>
          <span className="name">Anish</span>
        </div>
      </div>
    </header>
  );
}
