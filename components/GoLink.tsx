"use client";

import { trackGoal } from "@/lib/metrika";

// Ссылка наружу через /go/ (late-binding реф). Фиксируем цель ref_click в момент клика
// (переход — server-redirect route, pageview не сработает, поэтому JS-цель).
export function GoLink({ href, label }: { href: string; label: string }) {
  return (
    <a className="muted" style={{ fontSize: 13 }} href={href} target="_blank" rel="noopener noreferrer" onClick={() => trackGoal("ref_click")}>
      {label} →
    </a>
  );
}
