"use client";

import { deleteEstimate } from "@/app/estimate-actions";

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
      <button type="submit" className="icon-del" aria-label={`Удалить ${label}`} title="Удалить расчёт">×</button>
    </form>
  );
}
