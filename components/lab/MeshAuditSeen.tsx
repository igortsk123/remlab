"use client";

// Страница открыта → карточки на ней помечаются просмотренными (прогресс «проверено X из N»).
// Решение владельца 05.09: с одной кнопкой «переделать» молчание неотличимо от «не смотрел».

import { useEffect } from "react";
import { markSeen } from "@/lib/mesh-audit/client";

export function MeshAuditSeen({ itemIds }: { itemIds: number[] }) {
  const key = itemIds.join(",");
  useEffect(() => {
    const ids = key ? key.split(",").map(Number) : [];
    void markSeen(ids);
  }, [key]);
  return null;
}
