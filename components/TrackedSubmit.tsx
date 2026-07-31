"use client";

import { Button } from "@/components/base/buttons/button";
import { trackGoal } from "@/lib/metrika";

// Submit-кнопка внутри server-action формы: цель Метрики фиксируем в момент клика
// (после submit — server-redirect, клиентский код уже не выполнится).
export function TrackedSubmit({ goal, label, className }: { goal: string; label: string; className?: string }) {
  return (
    <Button type="submit" size="lg" className={className} onClick={() => trackGoal(goal)}>
      {label}
    </Button>
  );
}
