"use client";

import { useCallback, useEffect, useState } from "react";
import type { CalcKind, CalcProject, Room } from "@/contracts/calc";
import { loadProject, saveProject } from "@/lib/calc/storage";
import { addRoom, duplicateRoom, emptyProject, removeRoom, renameRoom, updateRoom } from "@/lib/calc/state";

const uid = () => Math.random().toString(36).slice(2, 10);
const nowIso = () => new Date().toISOString();

// Клиентское состояние проекта расчёта: инициализация из localStorage (или пустой проект),
// автосохранение при изменении, CRUD и точечное обновление комнат поверх lib/calc/state.
export function useCalcProject(kind: CalcKind) {
  const [project, setProject] = useState<CalcProject | null>(null);

  useEffect(() => {
    setProject(loadProject(kind) ?? emptyProject(kind, uid, nowIso()));
  }, [kind]);

  useEffect(() => {
    if (project) saveProject(project);
  }, [project]);

  const add = useCallback(() => setProject((p) => (p ? addRoom(p, uid, nowIso()) : p)), []);
  const remove = useCallback((id: string) => setProject((p) => (p ? removeRoom(p, id, nowIso()) : p)), []);
  const rename = useCallback(
    (id: string, name: string) => setProject((p) => (p ? renameRoom(p, id, name, nowIso()) : p)),
    [],
  );
  const duplicate = useCallback(
    (id: string) => setProject((p) => (p ? duplicateRoom(p, id, uid, nowIso()) : p)),
    [],
  );
  const update = useCallback(
    (id: string, fn: (r: Room) => Room) => setProject((p) => (p ? updateRoom(p, id, fn, nowIso()) : p)),
    [],
  );
  const reset = useCallback(() => setProject(emptyProject(kind, uid, nowIso())), [kind]);

  return { project, add, remove, rename, duplicate, update, reset };
}
