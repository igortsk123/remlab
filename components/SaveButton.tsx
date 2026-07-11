"use client";

import { trackGoal } from "@/lib/metrika";

// Кнопка «Сохранить» внутри server-action формы: цель estimate_saved фиксируем в момент клика
// (после submit — server-redirect, клиентский код уже не выполнится).
export function SaveButton() {
  return (
    <button type="submit" className="btn" onClick={() => trackGoal("estimate_saved")}>
      Сохранить в «Мои сметы»
    </button>
  );
}
