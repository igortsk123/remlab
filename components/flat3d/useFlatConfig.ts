"use client";

// Состояние конфигуратора: выбор покупателя + производные (сцена, цена).
// Чистая логика живёт в `lib/configurator/*`, здесь только React-обвязка — как у калькулятора
// (`components/calc/useCalcProject.ts`): флаг `hydrated` обязателен, иначе автосейв затирает
// черновик до его загрузки.

import { useCallback, useEffect, useMemo, useState } from "react";

import type { Apartment } from "@/contracts/apartment";
import type { Catalogue, Configuration } from "@/contracts/configurator";
import { defaultConfiguration, resolveScene, type ResolvedScene } from "@/lib/configurator/resolve";
import { loadDraft, saveDraft } from "@/lib/configurator/storage";

export interface FlatConfigState {
  config: Configuration;
  scene: ResolvedScene;
  hydrated: boolean;
  choose: (slotId: string, optionId: string) => void;
  /** Запомнить, куда покупатель передвинул/повернул предмет (версия подбора 2). */
  moveSlot: (slotId: string, to: { x: number; y: number; rot: number }) => void;
  /** Вернуть предмет на место застройщика. */
  resetSlotPlacement: (slotId: string) => void;
  reset: () => void;
  isDefault: boolean;
}

export function useFlatConfig(
  apartment: Apartment,
  catalogue: Catalogue,
  initial?: Configuration | null,
): FlatConfigState {
  const base = useMemo(() => defaultConfiguration(apartment, catalogue), [apartment, catalogue]);
  const [config, setConfig] = useState<Configuration>(initial ?? base);
  const [hydrated, setHydrated] = useState(Boolean(initial));

  useEffect(() => {
    if (initial) return; // пришли по ссылке на чужой подбор — черновик не подмешиваем
    setConfig(loadDraft(apartment.id) ?? base);
    setHydrated(true);
  }, [apartment.id, base, initial]);

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
      setConfig((c) => {
        const selections = { ...c.selections };
        for (const id of ids) selections[id] = optionId;
        return { ...c, selections, updatedAt: new Date().toISOString() };
      });
    },
    [apartment.slots],
  );

  const moveSlot = useCallback((slotId: string, to: { x: number; y: number; rot: number }) => {
    setConfig((c) => ({
      ...c,
      version: 2,
      placements: { ...(c.placements ?? {}), [slotId]: { x: to.x, y: to.y, rot: to.rot } },
      updatedAt: new Date().toISOString(),
    }));
  }, []);

  const resetSlotPlacement = useCallback((slotId: string) => {
    setConfig((c) => {
      const next = { ...(c.placements ?? {}) };
      delete next[slotId];
      return { ...c, placements: next, updatedAt: new Date().toISOString() };
    });
  }, []);

  const reset = useCallback(() => setConfig(base), [base]);

  const isDefault = useMemo(
    () =>
      Object.entries(base.selections).every(([k, v]) => config.selections[k] === v) &&
      Object.keys(config.placements ?? {}).length === 0,
    [base, config],
  );

  return { config, scene, hydrated, choose, moveSlot, resetSlotPlacement, reset, isDefault };
}
