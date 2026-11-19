// Клиентский слой /lab/cutout-check (T-20261119-104): нажатия «ок»/«не ок» и версии «что не так». Сеть отдельно от UI (code-standards).
// Версии текста идут через ту же сохранялку, что у /lab/mesh-check (`lib/mesh-audit/note-saver.ts`, она не знает про адрес) — адреса свои.

import type { NotePayload } from "@/lib/mesh-audit/note-saver";
import type { CutoutItemView } from "./types";
import type { Mark } from "./rules";

export { nonce, editorId } from "@/lib/mesh-audit/check-client";
import { nonce } from "@/lib/mesh-audit/check-client";

export type MarkOutcome =
  | { kind: "ok"; item: CutoutItemView }
  | { kind: "login" }
  | { kind: "error"; code?: string; message: string; item?: CutoutItemView };

const MARKS = "/api/lab/cutout-check/marks";
const NOTES = "/api/lab/cutout-check/notes";
const VIEWS = "/api/lab/cutout-check/views";

/** Одно нажатие = один idem_key: повтор того же запроса (сеть, двойной тап) не даёт второй строки журнала. expected — отметка, которую видит вкладка. */
export async function sendPress(item: Pick<CutoutItemView, "id" | "generationKey" | "mark">, press: Mark, reviewer: string): Promise<MarkOutcome> {
  const expected = item.mark === "ok" || item.mark === "bad" ? item.mark : null;
  try {
    const r = await fetch(MARKS, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ itemId: item.id, generationKey: item.generationKey, press, expected, reviewer, idemKey: nonce() }),
    });
    if (r.status === 401) return { kind: "login" };
    const data = (await r.json().catch(() => ({}))) as { item?: CutoutItemView; error?: string; code?: string };
    if (!r.ok || !data.item) return { kind: "error", code: data.code, message: data.error ?? `HTTP ${r.status}`, item: data.item };
    return { kind: "ok", item: data.item };
  } catch (e) {
    return { kind: "error", message: e instanceof Error ? e.message : "нет связи" };
  }
}

export async function sendNote(p: NotePayload): Promise<boolean> {
  try {
    const r = await fetch(NOTES, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p), keepalive: true });
    return r.ok;
  } catch {
    return false;
  }
}

/** Закрытие вкладки: sendBeacon (кука своего сайта уходит), нет его — fetch keepalive. */
export function beaconNote(p: NotePayload): boolean {
  const body = JSON.stringify(p);
  if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
    if (navigator.sendBeacon(NOTES, new Blob([body], { type: "application/json" }))) return true;
  }
  void fetch(NOTES, { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true }).catch(() => undefined);
  return true;
}

/** «Просмотрено» — карточка побыла на экране ≥ 1 с. Тихо: сбой не мешает работе, карточка просто останется непросмотренной до следующего показа. */
export async function sendView(item: Pick<CutoutItemView, "id" | "generationKey">, reviewer: string): Promise<boolean> {
  try {
    const r = await fetch(VIEWS, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ itemId: item.id, generationKey: item.generationKey, reviewer, opId: nonce() }),
      keepalive: true,
    });
    return r.ok;
  } catch {
    return false;
  }
}
