"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const ICONS: Record<string, React.ReactNode> = {
  dashboard: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" />
    </svg>
  ),
  meetings: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4" />
    </svg>
  ),
  tasks: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M9 6h11M9 12h11M9 18h11" /><path d="m3.5 5.5 1 1 2-2M3.5 11.5l1 1 2-2M3.5 17.5l1 1 2-2" />
    </svg>
  ),
  chat: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M21 12a8 8 0 0 1-8 8H5l-2 2V12a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8Z" />
    </svg>
  ),
  gantt: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M3 5h10M3 12h14M3 19h7" strokeLinecap="round" />
    </svg>
  ),
  people: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4.5-6.2" />
    </svg>
  ),
  availability: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" strokeLinecap="round" />
    </svg>
  ),
};

const GROUPS: { label: string; links: { href: string; label: string; icon: string }[] }[] = [
  {
    label: "Overview",
    links: [
      { href: "/", label: "Dashboard", icon: "dashboard" },
      { href: "/meetings", label: "Meetings", icon: "meetings" },
      { href: "/tasks", label: "My Tasks", icon: "tasks" },
    ],
  },
  {
    label: "Planning",
    links: [
      { href: "/chat", label: "Chat", icon: "chat" },
      { href: "/gantt", label: "Gantt", icon: "gantt" },
    ],
  },
  {
    label: "Settings",
    links: [
      { href: "/settings/people", label: "People", icon: "people" },
      { href: "/settings/availability", label: "Availability", icon: "availability" },
    ],
  },
];

function applyTheme(theme: string) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("theme", theme);
}

/** Sidebar nav — also rendered inside the mobile glass drawer. */
export default function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const [theme, setTheme] = useState("dark");

  useEffect(() => {
    const saved = localStorage.getItem("theme") ?? "dark";
    setTheme(saved);
    applyTheme(saved);
  }, []);

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
  }

  return (
    <>
      <Link href="/" className="sb-logo" onClick={onNavigate}>
        <div className="sb-logo-mark">S</div>
        <div>
          <div className="sb-logo-name">Self Planner</div>
          <div className="sb-logo-sub">AI Meeting Assistant</div>
        </div>
      </Link>
      {GROUPS.map((g) => (
        <div key={g.label}>
          <div className="sb-eyebrow">{g.label}</div>
          {g.links.map(({ href, label, icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={`sb-row ${active ? "active" : ""}`}
                aria-current={active ? "page" : undefined}
                onClick={onNavigate}
              >
                {ICONS[icon]}
                {label}
              </Link>
            );
          })}
        </div>
      ))}
      <div className="sb-footer">
        <button className="theme-toggle" onClick={toggleTheme}>
          {theme === "dark" ? (
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" strokeLinecap="round" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
            </svg>
          )}
          {theme === "dark" ? "Light Mode" : "Dark Mode"}
        </button>
        <div className="sb-user">
          <div className="sb-avatar">AN</div>
          <div>
            <div className="sb-user-name">Anish</div>
            <div className="sb-user-sub">Personal plan</div>
          </div>
        </div>
      </div>
    </>
  );
}
