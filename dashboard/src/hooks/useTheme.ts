// Light / dark theme. Default follows the OS setting; a choice made with the toggle is
// remembered in localStorage (which can be unavailable, e.g. in a private window).

import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "mhm-theme";

function readStored(): Theme | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

function writeStored(theme: Theme): void {
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    // not remembered; the toggle still works for this visit
  }
}

const darkQuery = () => window.matchMedia?.("(prefers-color-scheme: dark)");

export function useTheme(): [Theme, () => void] {
  const [stored, setStored] = useState<Theme | null>(readStored);
  const [osDark, setOsDark] = useState<boolean>(() => darkQuery()?.matches ?? false);

  useEffect(() => {
    const q = darkQuery();
    if (!q) return;
    const onChange = (e: MediaQueryListEvent) => setOsDark(e.matches);
    q.addEventListener("change", onChange);
    return () => q.removeEventListener("change", onChange);
  }, []);

  const theme: Theme = stored ?? (osDark ? "dark" : "light");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggle = useCallback(() => {
    const nextTheme: Theme = theme === "dark" ? "light" : "dark";
    writeStored(nextTheme);
    setStored(nextTheme);
  }, [theme]);

  return [theme, toggle];
}
