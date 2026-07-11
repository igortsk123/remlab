"use client";

import { trackGoal } from "@/lib/metrika";

// Кнопка внутри server-action формы пейволла: фиксирует цель Метрики в момент клика
// (после submit происходит server-redirect, клиентский код уже не выполнится).
export function PayButton({ label }: { label: string }) {
  return (
    <button className="btn btn-block" type="submit" onClick={() => trackGoal("pack_unlocked")}>
      {label}
    </button>
  );
}
