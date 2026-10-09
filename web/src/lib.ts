import { useEffect, useState } from "react";

/** localStorage that never throws (private windows, blocked storage). */
export const storage = {
  get(key: string, fallback = ""): string {
    try {
      return localStorage.getItem(key) ?? fallback;
    } catch {
      return fallback;
    }
  },
  set(key: string, value: string) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* ignore */
    }
  },
};

export type Theme = "system" | "light" | "dark";

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => (storage.get("sma.theme", "system") as Theme) || "system");
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    storage.set("sma.theme", theme);
  }, [theme]);
  return [theme, setTheme];
}

export function usePersistent(key: string, initial = ""): [string, (v: string) => void] {
  const [value, setValue] = useState(() => storage.get(key, initial));
  return [value, (v: string) => (setValue(v), storage.set(key, v))];
}

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function relativeTime(iso?: string | null): string {
  if (!iso) return "";
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 7 * 86400) return `${Math.floor(seconds / 86400)}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function greeting(name: string): string {
  const hour = new Date().getHours();
  const part = hour < 5 ? "Working late" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  return `${part}, ${name.split(" ")[0] || "there"}.`;
}

export const hasArabic = (text: string) => /[؀-ۿ]/.test(text);

export const cx = (...names: (string | false | null | undefined)[]) => names.filter(Boolean).join(" ");
