/** Human-friendly date labels for task due dates (input: "YYYY-MM-DD"). */

const DAY_MS = 86_400_000;

function parseISODate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function formatDue(iso: string, now: Date = new Date()): { label: string; overdue: boolean } {
  const due = parseISODate(iso);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffDays = Math.round((due.getTime() - today.getTime()) / DAY_MS);

  if (diffDays < 0) {
    const n = -diffDays;
    return { label: `overdue by ${n} day${n === 1 ? "" : "s"}`, overdue: true };
  }
  if (diffDays === 0) return { label: "due today", overdue: false };
  if (diffDays === 1) return { label: "due tomorrow", overdue: false };

  const opts: Intl.DateTimeFormatOptions =
    due.getFullYear() === today.getFullYear()
      ? { weekday: "short", day: "numeric", month: "short" }
      : { day: "numeric", month: "short", year: "numeric" };
  return { label: `due ${due.toLocaleDateString("en-GB", opts)}`, overdue: false };
}
