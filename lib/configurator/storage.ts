// Черновик конфигурации в браузере. По образцу `lib/calc/storage.ts`: SSR-safe, версия в ключе,
// разбор через Zod, любые сбои (приватный режим, квота) — молча в no-op.

import { configuration, type Configuration } from "@/contracts/configurator";

const KEY = "remlab.flat3d.v1";

export function loadDraft(apartmentId: string): Configuration | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(`${KEY}.${apartmentId}`);
    if (!raw) return null;
    const parsed = configuration.safeParse(JSON.parse(raw));
    return parsed.success && parsed.data.apartmentId === apartmentId ? parsed.data : null;
  } catch {
    return null;
  }
}

export function saveDraft(cfg: Configuration): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(`${KEY}.${cfg.apartmentId}`, JSON.stringify(cfg));
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
