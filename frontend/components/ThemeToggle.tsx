"use client";

import { useLayoutEffect, useState } from "react";
import { ProductIcon } from "./ProductIcon";

type Theme = "light" | "dark";

function currentTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem("careeros-theme");
  if (stored === "dark" || stored === "light") return stored;
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(currentTheme);

  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    window.localStorage.setItem("careeros-theme", next);
    setTheme(next);
  }

  return (
    <button className="icon-button theme-toggle" type="button" onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} suppressHydrationWarning>
      <ProductIcon name={theme === "dark" ? "sun" : "moon"} />
    </button>
  );
}
