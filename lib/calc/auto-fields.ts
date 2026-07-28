// Источник значений параметров (П5): какие поля заполнены АВТО (из ссылки), какие руками.
// Правило: новая ссылка стирает ТОЛЬКО прежние авто-значения; ручные правки сохраняются и
// снимают пометку «авто» со своего поля. Чистые функции — тест tests/unit/auto-fields.test.ts.

import type { MaterialSpec } from "@/contracts/calc";

export type SpecKey = keyof MaterialSpec;

// Применить авто-спеку из ссылки: убрать прежние авто-поля, накатить новые, пересчитать список авто.
export function applyAutoSpec(
  spec: MaterialSpec,
  autoKeys: string[] | undefined,
  incoming: Partial<MaterialSpec>,
): { spec: MaterialSpec; autoKeys: string[] } {
  const next: MaterialSpec = { ...spec };
  for (const k of autoKeys ?? []) delete next[k as SpecKey]; // прежние авто — стираем (ручные не в списке)
  Object.assign(next, incoming);
  return { spec: next, autoKeys: Object.keys(incoming) };
}

// Ручная правка поля: значение меняет вызывающий, здесь — снять пометку «авто» с этих ключей.
export function manualKeys(autoKeys: string[] | undefined, patch: Partial<MaterialSpec>): string[] {
  const touched = new Set(Object.keys(patch));
  return (autoKeys ?? []).filter((k) => !touched.has(k));
}
