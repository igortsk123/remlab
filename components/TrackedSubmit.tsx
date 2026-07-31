"use client";

import { trackGoal } from "@/lib/metrika";

// Submit-кнопка внутри server-action формы: цель Метрики фиксируем в момент клика
// (после submit — server-redirect, клиентский код уже не выполнится).
export function TrackedSubmit({ goal, label, className = "btn" }: { goal: string; label: string; className?: string }) {
  return (
    <button type="submit" className={className} onClick={() => trackGoal(goal)}>
      {label}
    </button>
  );
}
