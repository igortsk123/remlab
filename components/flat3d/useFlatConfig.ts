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

  const choose = useCallback((slotId: string, optionId: string) => {
    setConfig((c) => ({
      ...c,
      selections: { ...c.selections, [slotId]: optionId },
      updatedAt: new Date().toISOString(),
    }));
  }, []);

  const reset = useCallback(() => setConfig(base), [base]);

  const isDefault = useMemo(
    () => Object.entries(base.selections).every(([k, v]) => config.selections[k] === v),
    [base, config],
  );

  return { config, scene, hydrated, choose, reset, isDefault };
}
