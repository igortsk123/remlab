"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/base/badges/badges";

// Бейдж-счётчик сохранённых расчётов у «Моей лаборатории» (шапка, плитка главной).
// Грузится с клиента (/api/lab/count) — страницы остаются статическими; 0 → ничего не рендерим.
export function LabBadge() {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let alive = true;
    fetch("/api/lab/count")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive && d && typeof d.count === "number") setCount(d.count); })
      .catch(() => { /* сеть/ошибка — бейдж просто не показываем */ });
    return () => { alive = false; };
  }, []);

  if (count <= 0) return null;
  return (
    <span aria-label={`Сохранённых расчётов: ${count}`} className="ml-2 inline-block align-middle">
      <Badge type="pill-color" color="brand" size="sm">{count}</Badge>
    </span>
  );
}
