"use client";

// Состояние конфигуратора: выбор покупателя + производные (сцена, цена).
// Чистая логика живёт в `lib/configurator/*`, здесь только React-обвязка — как у калькулятора
// (`components/calc/useCalcProject.ts`): флаг `hydrated` обязателен, иначе автосейв затирает
// черновик до его загрузки.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { Apartment } from "@/contracts/apartment";
import type { Catalogue, Configuration } from "@/contracts/configurator";
import { defaultConfiguration, resolveScene, type ResolvedScene } from "@/lib/configurator/resolve";
import { baseSnapshotOf, staleSlots } from "@/lib/configurator/fromDemo";
import { loadDraft, saveDraft } from "@/lib/configurator/storage";
import { emptyHistory, record, redo as redoH, undo as undoH, type History } from "@/lib/configurator/history";

export interface FlatConfigState {
  config: Configuration;
  scene: ResolvedScene;
  hydrated: boolean;
  choose: (slotId: string, optionId: string) => void;
  /** Запомнить, куда покупатель передвинул/повернул предмет (версия подбора 2). */
  moveSlot: (slotId: string, to: { x: number; y: number; rot: number }) => void;
  /** Вернуть предмет на место застройщика. */
  resetSlotPlacement: (slotId: string) => void;
  /** Убрать предмет из комнаты / вернуть его (кнопка «Убрать» у предмета, flat3d-sims-ux). */
  hideSlot: (slotId: string) => void;
  unhideSlot: (slotId: string) => void;
  reset: () => void;
  /** Отмена и возврат любого действия покупателя (выбор, группа стульев, перемещение, поворот, «убрать», сброс). */
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  isDefault: boolean;
}

export function useFlatConfig(
  apartment: Apartment,
  catalogue: Catalogue,
  initial?: Configuration | null,
): FlatConfigState {
  // открыт из коллекции — её номер остаётся и после «Сброса» (иначе сохранённая ссылка открыла бы исходный набор)
  const collId = initial?.collectionId;
  const base = useMemo(
    () => ({ ...defaultConfiguration(apartment, catalogue), ...(collId ? { collectionId: collId } : {}) }),
    [apartment, catalogue, collId],
  );
  const [config, setConfig] = useState<Configuration>(initial ?? base);
  const [hydrated, setHydrated] = useState(Boolean(initial));
  const [hist, setHist] = useState<History<Configuration>>(emptyHistory);
  const now = useRef(config);
  now.current = config;

  // Каждое действие покупателя — через commit: прежний подбор уходит в историю (отмена), будущее сбрасывается.
  // Не внутри функции-обновителя setConfig: в строгом режиме React зовёт её дважды и история удвоилась бы.
  const commit = useCallback((fn: (c: Configuration) => Configuration) => {
    const before = now.current;
    const next = fn(before);
    if (next === before) return;
    now.current = next;
    setHist((h) => record(h, before));
    setConfig(next);
  }, []);

  useEffect(() => {
    if (initial) return; // пришли по ссылке на чужой подбор — черновик не подмешиваем
    // Черновик сверяется с текущим набором витрины так же, как сохранённая ссылка: модель на месте
    // сменилась после ночной пересборки — выбор и перестановка этого места не переносятся (verify 13.10).
    const draft = loadDraft(apartment.id, apartment.baseVariant);
    const stale = draft ? staleSlots(draft, baseSnapshotOf(apartment, catalogue)) : [];
    const keep = <T,>(rec: Record<string, T>) => Object.fromEntries(Object.entries(rec).filter(([k]) => !stale.includes(k)));
    setConfig(draft ? { ...draft, selections: keep(draft.selections), placements: keep(draft.placements ?? {}),
      hidden: (draft.hidden ?? []).filter((id) => !stale.includes(id)) } : base);
    setHydrated(true);
  }, [apartment, catalogue, base, initial]);

  useEffect(() => {
    if (hydrated) saveDraft(config);
  }, [config, hydrated]);

  const scene = useMemo(() => resolveScene(apartment, catalogue, config), [apartment, catalogue, config]);

  const choose = useCallback(
    (slotId: string, optionId: string) => {
      // Группа совместной замены: стулья за одним столом меняются ВСЕ разом — разнобой за столом
      // никто не ставит (владелец 30.09). Группа объявлена в слоте, а не угадывается по названию.
      const group = apartment.slots.find((s) => s.id === slotId)?.selectionGroup;
      const ids = group
        ? apartment.slots.filter((s) => s.selectionGroup === group).map((s) => s.id)
        : [slotId];
      commit((c) => {
        const selections = { ...c.selections };
        for (const id of ids) selections[id] = optionId;
        // выбрали вариант для убранного предмета — значит, он снова нужен
        const hidden = c.hidden?.filter((id) => !ids.includes(id));
        return { ...c, selections, ...(hidden ? { hidden } : {}), updatedAt: new Date().toISOString() };
      });
    },
    [apartment.slots, commit],
  );

  const moveSlot = useCallback((slotId: string, to: { x: number; y: number; rot: number }) => {
    commit((c) => ({
      ...c,
      version: 3,
      placements: { ...(c.placements ?? {}), [slotId]: { x: to.x, y: to.y, rot: to.rot } },
      updatedAt: new Date().toISOString(),
    }));
  }, [commit]);

  const resetSlotPlacement = useCallback((slotId: string) => {
    commit((c) => {
      const next = { ...(c.placements ?? {}) };
      delete next[slotId];
      return { ...c, placements: next, updatedAt: new Date().toISOString() };
    });
  }, [commit]);

  const hideSlot = useCallback((slotId: string) => {
    commit((c) => (c.hidden?.includes(slotId) ? c : { ...c, hidden: [...(c.hidden ?? []), slotId], updatedAt: new Date().toISOString() }));
  }, [commit]);

  const unhideSlot = useCallback((slotId: string) => {
    commit((c) => (c.hidden?.includes(slotId) ? { ...c, hidden: c.hidden.filter((id) => id !== slotId), updatedAt: new Date().toISOString() } : c));
  }, [commit]);

  const reset = useCallback(() => commit(() => base), [base, commit]);

  const undo = useCallback(() => {
    const r = undoH(hist, now.current);
    if (!r) return;
    now.current = r.value;
    setHist(r.h);
    setConfig(r.value);
  }, [hist]);

  const redo = useCallback(() => {
    const r = redoH(hist, now.current);
    if (!r) return;
    now.current = r.value;
    setHist(r.h);
    setConfig(r.value);
  }, [hist]);

  const isDefault = useMemo(
    () =>
      Object.entries(base.selections).every(([k, v]) => config.selections[k] === v) &&
      Object.keys(config.placements ?? {}).length === 0 &&
      (config.hidden ?? []).length === 0,
    [base, config],
  );

  return {
    config, scene, hydrated, choose, moveSlot, resetSlotPlacement, hideSlot, unhideSlot, reset,
    undo, redo, canUndo: hist.past.length > 0, canRedo: hist.future.length > 0, isDefault,
  };
}
