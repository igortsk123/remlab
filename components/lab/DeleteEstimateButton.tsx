"use client";

import { deleteEstimate } from "@/app/estimate-actions";
import { Button } from "@/components/base/buttons/button";

// Кнопка «удалить расчёт» в лаборатории: нативный confirm перед server action (без модалки).
export function DeleteEstimateButton({ estimateId, label }: { estimateId: string; label: string }) {
  return (
    <form
      action={deleteEstimate}
      onSubmit={(e) => {
        if (!window.confirm(`Удалить «${label}»? Отменить будет нельзя.`)) e.preventDefault();
      }}
    >
      <input type="hidden" name="id" value={estimateId} />
      {/* Тап-зона ≥44px (min-w/h-11). */}
      <Button type="submit" color="tertiary" size="sm" className="-my-2.5 min-h-11 min-w-11 text-xl text-fg-quaternary hover:text-error-primary" aria-label={`Удалить ${label}`}>×</Button>
    </form>
  );
}
