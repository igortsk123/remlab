"use client";

import { useCallback, useEffect, useState } from "react";
import type { CalcKind, CalcProject, Room } from "@/contracts/calc";
import { loadProject, saveProject } from "@/lib/calc/storage";
import { addRoom, duplicateRoom, removeRoom, renameRoom, updateRoom } from "@/lib/calc/state";

const uid = () => Math.random().toString(36).slice(2, 10);
const nowIso = () => new Date().toISOString();

// Стабильный стартовый проект (одинаков на сервере и клиенте — без random/Date) → корректный SSR
// без «мигания загрузки»; реальные данные из localStorage подгружаются в useEffect на клиенте.
function initialProject(kind: CalcKind): CalcProject {
  return { version: 1, kind, rooms: [{ id: "r1", name: "Комната 1", surfaces: [], material: {} }], updatedAt: "" };
}

export function useCalcProject(kind: CalcKind) {
  const [project, setProject] = useState<CalcProject>(() => initialProject(kind));
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setProject(loadProject(kind) ?? initialProject(kind));
    setHydrated(true);
  }, [kind]);

  useEffect(() => {
    if (hydrated) saveProject(project);
  }, [project, hydrated]);

  const add = useCallback(() => setProject((p) => addRoom(p, uid, nowIso())), []);
  const remove = useCallback((id: string) => setProject((p) => removeRoom(p, id, nowIso())), []);
  const rename = useCallback((id: string, name: string) => setProject((p) => renameRoom(p, id, name, nowIso())), []);
  const duplicate = useCallback((id: string) => setProject((p) => duplicateRoom(p, id, uid, nowIso())), []);
  const update = useCallback((id: string, fn: (r: Room) => Room) => setProject((p) => updateRoom(p, id, fn, nowIso())), []);
  const reset = useCallback(() => setProject(initialProject(kind)), [kind]);

  return { project, add, remove, rename, duplicate, update, reset };
}
