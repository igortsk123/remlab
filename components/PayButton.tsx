"use client";

import { Button } from "@/components/base/buttons/button";
import { trackGoal } from "@/lib/metrika";

// Кнопка внутри server-action формы пейволла: фиксирует цель Метрики в момент клика
// (после submit происходит server-redirect, клиентский код уже не выполнится).
export function PayButton({ label }: { label: string }) {
  return (
    <Button type="submit" size="lg" className="w-full" onClick={() => trackGoal("pack_unlocked")}>
      {label}
    </Button>
  );
}
