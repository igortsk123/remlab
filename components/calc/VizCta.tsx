"use client";

import { useTransition } from "react";
import { startCalcViz } from "@/app/viz-actions";

// Хвост из результата: визуализация комнаты по фото (ступень M5). Оплата 60 ₽ — на сервере, если настроена.
export function VizCta() {
  const [pending, startTransition] = useTransition();
  return (
    <div className="card stack">
      <p className="eyebrow">Как это будет выглядеть</p>
      <p className="muted" style={{ margin: 0, fontSize: 15 }}>
        Загрузите фото комнаты и посмотрите, как будет выглядеть ваша комната после обновления отделки.
      </p>
      <button
        className="btn btn-secondary"
        disabled={pending}
        onClick={() => startTransition(() => { void startCalcViz(); })}
      >
        {pending ? "…" : "Посмотреть комнату в новом дизайне"}
      </button>
    </div>
  );
}
