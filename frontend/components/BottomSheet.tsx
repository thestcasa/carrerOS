"use client";
import { useEffect, useRef, type ReactNode } from "react";
import { ProductIcon } from "./ProductIcon";
const focusable = "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])";
export function BottomSheet({ open, title, description, children, onClose }: { open: boolean; title: string; description?: string; children: ReactNode; onClose: () => void }) {
  const dialog = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!open) return;
    returnFocus.current = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const node = dialog.current;
    (node?.querySelector<HTMLElement>(focusable) ?? node)?.focus();
    function keydown(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab" || !node) return;
      const items = [...node.querySelectorAll<HTMLElement>(focusable)];
      if (!items.length) { event.preventDefault(); return; }
      const first = items[0]; const last = items.at(-1)!;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", keydown);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener("keydown", keydown); returnFocus.current?.focus(); };
  }, [onClose, open]);
  if (!open) return null;
  return <div className="sheet-layer" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><div ref={dialog} className="bottom-sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title" tabIndex={-1}>
    <div className="sheet-handle" aria-hidden="true" /><header className="sheet-header"><div><h2 id="sheet-title">{title}</h2>{description ? <p className="muted">{description}</p> : null}</div><button className="icon-button" type="button" onClick={onClose} aria-label={`Close ${title}`}><ProductIcon name="close" /></button></header><div className="sheet-content">{children}</div>
  </div></div>;
}
