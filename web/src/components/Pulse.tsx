import { cx } from "../lib";

// One heartbeat: flat, P wave, QRS spike, T wave, flat. Repeated for a trace.
const BEAT = "h18 q4 -6 8 0 h6 l3 4 l5 -26 l5 34 l4 -12 h8 q6 -9 12 0 h14";

export function Pulse({ beats = 3, active = true, className }: { beats?: number; active?: boolean; className?: string }) {
  const width = beats * 79;
  const d = `M0 22 ${Array.from({ length: beats }, () => BEAT).join(" ")}`;
  return (
    <svg className={cx("pulse", active && "is-active", className)} viewBox={`0 0 ${width} 44`} aria-hidden="true">
      <path className="pulse-ghost" d={d} pathLength={100} />
      <path className="pulse-trace" d={d} pathLength={100} />
    </svg>
  );
}

export function Logo({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="logo">
      <rect width="32" height="32" rx="9" className="logo-bg" />
      <path d="M4 17h6l2-5 4 10 3-8 2 3h7" className="logo-line" />
    </svg>
  );
}
