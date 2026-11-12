// Готовые снимки карточек комнат тура (T-20261112-29): воркер DEV снимает кадр 3D карточки той же страницей
// (`tools/scout/trial_cards.mjs`) и шлёт сюда JPEG с ключом расстановки (`index.html:trHsKey` — комната|вариант|номер состояния).

import { z } from "zod";

/** Ключ расстановки страницы: `<комната>|<вариант>|<номер состояния>` (`index.html:roomStateKey`). */
export const CARD_KEY_RE = /^[a-z0-9-]{1,40}\|[A-Za-z0-9_.-]{1,80}\|[A-Za-z0-9_-]{1,80}$/;
/** Файл снимка в папке задания: 16 знаков sha256 содержимого. */
export const CARD_FILE_RE = /^[a-f0-9]{16}\.jpg$/;
/** Потолок одного снимка (1024×723, JPEG 0,82 — 55–80 КБ, замер T-29) и снимков в одном запросе. */
export const CARD_MAX_BYTES = 400 * 1024;
export const CARDS_PER_POST = 8;

export const trialCardsIn = z.object({
  id: z.string().min(1).max(64),
  cards: z.array(z.object({
    key: z.string().regex(CARD_KEY_RE),
    // base64 без префикса data:
    jpg: z.string().min(100).max(Math.ceil((CARD_MAX_BYTES * 4) / 3) + 4).regex(/^[A-Za-z0-9+/]+={0,2}$/),
  })).min(1).max(CARDS_PER_POST),
});
export type TrialCardsIn = z.infer<typeof trialCardsIn>;
