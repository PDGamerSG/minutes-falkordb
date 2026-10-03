// Formatting helpers. All inputs are epoch milliseconds unless stated.

const dateFmt = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
});
const dateTimeFmt = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const fullFmt = new Intl.DateTimeFormat("en-GB", {
  year: "numeric",
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export function fmtDate(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return dateFmt.format(new Date(ms));
}

export function fmtDateTime(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return dateTimeFmt.format(new Date(ms));
}

export function fmtFull(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return fullFmt.format(new Date(ms));
}

export function fmtIso(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return new Date(ms).toISOString();
}

/** Offset inside a recording: 0:04:12 or 4:12. */
export function fmtClock(ms: number | null | undefined): string {
  if (ms == null) return "—";
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return `${h > 0 ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function fmtRelative(ms: number | null | undefined, now = Date.now()): string {
  if (ms == null) return "—";
  const diff = now - ms;
  const abs = Math.abs(diff);
  const suffix = diff >= 0 ? "ago" : "from now";
  if (abs < 45_000) return "just now";
  if (abs < 3_600_000) return `${Math.round(abs / 60_000)}m ${suffix}`;
  if (abs < 86_400_000) return `${Math.round(abs / 3_600_000)}h ${suffix}`;
  return `${Math.round(abs / 86_400_000)}d ${suffix}`;
}

export function fmtMs(n: number | null | undefined, digits = 1): string {
  if (n == null) return "—";
  return `${n.toFixed(digits)} ms`;
}

export function fmtPct(n: number | null | undefined, digits = 0): string {
  if (n == null) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

export function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-GB").format(n);
}

export function fmtMb(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n.toFixed(n < 10 ? 2 : 1)} MB`;
}

export function shortId(id: string | null | undefined, keep = 10): string {
  if (!id) return "—";
  return id.length <= keep ? id : `${id.slice(0, keep)}…`;
}

export function titleCase(s: string): string {
  return s.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
