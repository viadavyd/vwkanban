/** "just now", "3 min ago", "5 h ago", "2 d ago", else the date (YYYY-MM-DD). */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso);
  const s = Math.max(0, Math.round((now - then) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d} d ago`;
  return new Date(then).toISOString().slice(0, 10);
}
