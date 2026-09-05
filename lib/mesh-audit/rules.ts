// Чистые правила страницы ручной приёмки мешей (/lab/mesh-audit): страницы, партии, решение.
// Без БД и сети — их гоняет vitest; серверный слой (repo-*.ts) только вызывает.

export const PAGE_SIZE = 20;
export const BATCH_SIZE = 200; // ≈1,5 ГБ моделей на прод-диске, ~12 минут заливки
export const PAGES_PER_BATCH = BATCH_SIZE / PAGE_SIZE;
export const MAX_MANUAL_REDO = 2; // решение владельца 05.09: две ручные переделки на товар за всё время
export const PENDING_STATUSES: ReadonlySet<string> = new Set(["redo_requested", "redo_queued"]);

export type ItemStatus = "open" | "redo_requested" | "redo_queued" | "redo_blocked" | "replace_needed";
export type Verdict = "redo" | "replace_needed";

export function pageCount(total: number): number {
  return Math.max(1, Math.ceil(total / PAGE_SIZE));
}

export function clampPage(raw: string | undefined, pages: number): number {
  const n = Number.parseInt(raw ?? "1", 10);
  if (!Number.isFinite(n) || n < 1) return 1;
  return Math.min(n, pages);
}

export function batchOfPage(page: number): number {
  return Math.ceil(page / PAGES_PER_BATCH);
}

export function pagesOfBatch(batch: number): [number, number] {
  return [(batch - 1) * PAGES_PER_BATCH + 1, batch * PAGES_PER_BATCH];
}

export function batchCount(total: number): number {
  return Math.max(1, Math.ceil(total / BATCH_SIZE));
}

export interface ItemState {
  generationKey: string;
  manualAttempts: number;
  status: string;
}

export type DecisionCheck =
  | { ok: true; attemptNo: number; manualAttempts: number; status: ItemStatus }
  | { ok: false; http: number; code: "stale" | "pending" | "limit" | "too_early"; message: string };

// Решение владельца адресуется КОНКРЕТНОМУ поколению: клик из старой вкладки по уже заменённому
// мешу — 409, а не брак актуальной модели. Лимит считается за всё время жизни SKU.
export function checkDecision(item: ItemState, generationKey: string, verdict: Verdict): DecisionCheck {
  if (item.generationKey !== generationKey) {
    return { ok: false, http: 409, code: "stale", message: "меш уже заменён — обновите страницу" };
  }
  if (verdict === "redo") {
    if (PENDING_STATUSES.has(item.status)) return { ok: false, http: 409, code: "pending", message: "уже на переделке" };
    if (item.manualAttempts >= MAX_MANUAL_REDO) {
      return { ok: false, http: 409, code: "limit", message: `переделок больше нет (${MAX_MANUAL_REDO} из ${MAX_MANUAL_REDO}) — нужна замена товара/фото` };
    }
    return { ok: true, attemptNo: item.manualAttempts + 1, manualAttempts: item.manualAttempts + 1, status: "redo_requested" };
  }
  if (item.status === "replace_needed") return { ok: false, http: 409, code: "pending", message: "уже помечен «нужна замена»" };
  if (item.manualAttempts < MAX_MANUAL_REDO) return { ok: false, http: 400, code: "too_early", message: "сначала две переделки" };
  return { ok: true, attemptNo: item.manualAttempts + 1, manualAttempts: item.manualAttempts, status: "replace_needed" };
}

// Отмена случайного клика возможна, пока переделка не ушла в снимок очереди (redo_requested) —
// или для «нужна замена» (она никуда не едет). Что уже в очереди — не отменяем: задание поедет.
export type CancelCheck =
  | { ok: true; manualAttempts: number }
  | { ok: false; http: 409; code: "not_pending" | "queued"; message: string };

export function checkCancel(item: ItemState, generationKey: string, verdict: string): CancelCheck {
  if (item.generationKey !== generationKey) return { ok: false, http: 409, code: "not_pending", message: "меш уже заменён — обновите страницу" };
  if (item.status === "redo_queued") return { ok: false, http: 409, code: "queued", message: "уже в очереди — отменить нельзя" };
  if (item.status !== "redo_requested" && item.status !== "replace_needed") {
    return { ok: false, http: 409, code: "not_pending", message: "нечего отменять" };
  }
  return { ok: true, manualAttempts: verdict === "redo" ? Math.max(0, item.manualAttempts - 1) : item.manualAttempts };
}

// ACK конвейера → статус карточки. `done` статус не меняет: новое поколение приедет через push
// списка и само переведёт карточку в open с пометкой «сделан заново».
export function reworkToItemStatus(rework: string): ItemStatus | null {
  switch (rework) {
    case "queued":
    case "running":
      return "redo_queued";
    case "blocked":
      return "redo_blocked";
    case "requested":
    case "applied":
      return "redo_requested";
    default:
      return null;
  }
}
