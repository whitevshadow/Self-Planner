"use client";

import { useEffect, useRef, useState } from "react";
import Sidebar from "@/components/Sidebar";
import TopBar from "@/components/TopBar";

/** App shell: inset sidebar panel (desktop) / slide-over drawer (mobile). */
export default function Shell({ children }: { children: React.ReactNode }) {
  const [drawer, setDrawer] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);

  // Restore the rail state after mount. Reading localStorage during render
  // would desync server and client HTML, so the first paint is always expanded.
  useEffect(() => {
    setCollapsed(localStorage.getItem("sidebarCollapsed") === "true");
  }, []);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      localStorage.setItem("sidebarCollapsed", String(!prev));
      return !prev;
    });
  }

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
    <div className="shell" data-collapsed={collapsed ? "true" : undefined}>
      <aside className="sidebar">
        <Sidebar collapsed={collapsed} onToggleCollapse={toggleCollapsed} />
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
