// Черновик конфигурации в браузере. По образцу `lib/calc/storage.ts`: SSR-safe, версия в ключе,
// разбор через Zod, любые сбои (приватный режим, квота) — молча в no-op.

import { configuration, upgradeConfiguration, type Configuration } from "@/contracts/configurator";

const KEY = "remlab.flat3d.v1";

/** Черновик у квартиры свой на каждый исходный набор: «джапанди» и «лофт» одной квартиры — разные подборы. */
export const draftKey = (apartmentId: string, baseVariant?: string) => (baseVariant ? `${apartmentId}~${baseVariant}` : apartmentId);

export function loadDraft(apartmentId: string, baseVariant?: string): Configuration | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(`${KEY}.${draftKey(apartmentId, baseVariant)}`);
    if (!raw) return null;
    const parsed = configuration.safeParse(JSON.parse(raw));
    if (!parsed.success || parsed.data.apartmentId !== apartmentId || parsed.data.baseVariant !== baseVariant) return null;
    // черновик мог быть сохранён ДО появления координат мебели — поднимаем до версии 2
    return upgradeConfiguration(parsed.data);
  } catch {
    return null;
  }
}

export function saveDraft(cfg: Configuration): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(`${KEY}.${draftKey(cfg.apartmentId, cfg.baseVariant)}`, JSON.stringify(cfg));
  } catch {
    /* приватный режим или переполнение — черновик не критичен */
  }
}

export function clearDraft(apartmentId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(`${KEY}.${apartmentId}`);
  } catch {
    /* см. выше */
  }
}
