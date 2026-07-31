"use client";

import { Button } from "@/components/base/buttons/button";
import { trackGoal } from "@/lib/metrika";

// Submit-кнопка внутри server-action формы: цель Метрики фиксируем в момент клика
// (после submit — server-redirect, клиентский код уже не выполнится).
export function TrackedSubmit({ goal, label, className, color = "primary" }: { goal: string; label: string; className?: string; color?: "primary" | "secondary" }) {
  return (
    <Button type="submit" size="lg" color={color} className={className} onClick={() => trackGoal(goal)}>
      {label}
    </Button>
  );
}
