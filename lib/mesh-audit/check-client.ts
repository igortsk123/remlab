// Клиентский слой /lab/mesh-check (T-20261112-118): нажатия «ок»/«брак» и версии комментария. Сеть отдельно от UI (code-standards).

import type { NotePayload } from "./note-saver";
import type { AuditItemView } from "./types";

export type Press = "ok" | "bad";
export type MarkOutcome =
  | { kind: "ok"; item: AuditItemView; reason?: string }
  | { kind: "login" }
  | { kind: "error"; code?: string; message: string; item?: AuditItemView };

const MARKS = "/api/lab/mesh-audit/marks";
const NOTES = "/api/lab/mesh-audit/notes";

export function nonce(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

/** Метка вкладки для журнала версий комментария (кто из двух вкладок писал). */
export function editorId(): string {
  try {
    const k = "mesh-check-editor";
    const v = sessionStorage.getItem(k) ?? nonce();
    sessionStorage.setItem(k, v);
    return v;
  } catch {
    return nonce();
  }
}

/** Одно нажатие = один idem_key: повтор того же запроса (сеть, двойной клик) не даёт второй строки журнала. expected — отметка,
 * которую видит вкладка: другая вкладка успела раньше — сервер не применит молча, вернёт свежую карточку (409). */
export async function sendPress(item: Pick<AuditItemView, "id" | "generationKey" | "mark">, press: Press, reviewer: string): Promise<MarkOutcome> {
  try {
    const r = await fetch(MARKS, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ itemId: item.id, generationKey: item.generationKey, press, expected: item.mark ?? null, reviewer, idemKey: nonce() }),
    });
    if (r.status === 401) return { kind: "login" };
    const data = (await r.json().catch(() => ({}))) as { item?: AuditItemView; error?: string; code?: string; reason?: string };
    if (!r.ok || !data.item) return { kind: "error", code: data.code, message: data.error ?? `HTTP ${r.status}`, item: data.item };
    return { kind: "ok", item: data.item, reason: data.reason };
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
