"use client";

import { useCallback, useEffect, useState } from "react";
import type { CalcKind, CalcProject, Room } from "@/contracts/calc";
import { clearProject, loadProject, saveProject } from "@/lib/calc/storage";
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
  // Счётчик правок пользователя в текущем расчёте (0 — после открытия/подгрузки черновика и «новый расчёт»):
  // по нему цель «расчёт начат» отличает правку от подгрузки (`lib/calc/started-goal.ts`).
  const [edits, setEdits] = useState(0);

  useEffect(() => {
    setProject(loadProject(kind) ?? initialProject(kind));
    setHydrated(true);
  }, [kind]);

  useEffect(() => {
    if (hydrated) saveProject(project);
  }, [project, hydrated]);

  const edit = useCallback((fn: (p: CalcProject) => CalcProject) => {
    setProject(fn);
    setEdits((n) => n + 1);
  }, []);
  const add = useCallback(() => edit((p) => addRoom(p, uid, nowIso())), [edit]);
  const remove = useCallback((id: string) => edit((p) => removeRoom(p, id, nowIso())), [edit]);
  const rename = useCallback((id: string, name: string) => edit((p) => renameRoom(p, id, name, nowIso())), [edit]);
  const duplicate = useCallback((id: string) => edit((p) => duplicateRoom(p, id, uid, nowIso())), [edit]);
  const update = useCallback((id: string, fn: (r: Room) => Room) => edit((p) => updateRoom(p, id, fn, nowIso())), [edit]);
  const reset = useCallback(() => { setProject(initialProject(kind)); setEdits(0); }, [kind]);
  // «Новый расчёт»: очистить черновик localStorage и вернуть стартовый проект.
  const clear = useCallback(() => { clearProject(kind); setProject(initialProject(kind)); setEdits(0); }, [kind]);

  return { project, edits, add, remove, rename, duplicate, update, reset, clear };
}
