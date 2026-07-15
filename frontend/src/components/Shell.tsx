"use client";

import { useEffect, useRef, useState } from "react";
import Sidebar from "@/components/Sidebar";
import TopBar from "@/components/TopBar";

/** App shell: fixed glass sidebar (desktop) / slide-over drawer (mobile). */
export default function Shell({ children }: { children: React.ReactNode }) {
  const [drawer, setDrawer] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);

  // Focus trap + Esc for the mobile drawer (it acts as a modal dialog).
  useEffect(() => {
    if (!drawer) return;
    const el = drawerRef.current;
    el?.querySelector<HTMLElement>("a, button")?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setDrawer(false);
      if (e.key === "Tab" && el) {
        const items = el.querySelectorAll<HTMLElement>("a, button");
        if (items.length === 0) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <Sidebar />
      </aside>
      {drawer && (
        <>
          <div className="drawer-backdrop" onClick={() => setDrawer(false)} />
          <div className="glass-drawer" role="dialog" aria-modal="true" aria-label="Navigation" ref={drawerRef}>
            <Sidebar onNavigate={() => setDrawer(false)} />
          </div>
        </>
      )}
      <div className="content">
        <TopBar onMenu={() => setDrawer(true)} />
        <main>{children}</main>
      </div>
    </div>
  );
}
