// Комментарий на странице проверки мешей сохраняется САМ (T-20261112-118, образец — страница стилей): через 1 с после ввода,
// сразу при уходе из поля, при закрытии вкладки — sendBeacon. Ни одна буква не теряется: каждая версия до ответа сервера лежит
// ещё и в браузере (черновик), после перезагрузки досылается. Номер версии растёт монотонно — поздний ответ старой версии
// не затирает новую ни на сервере (`note_seq`), ни в значке «сохранено». У каждой версии свой opId: обычный запрос, маяк и
// досылка после перезагрузки одной версии дают одну строку журнала. Без DOM и сети — зависимости передаются (тесты).

export type SaveState = "idle" | "saving" | "saved" | "error";

export interface NotePayload {
  itemId: number;
  generationKey: string;
  body: string;
  seq: number;
  opId: string;
  editorId: string;
  reviewer: string;
}

export interface NoteSaverDeps {
  send: (p: NotePayload) => Promise<boolean>; // обычный запрос: true = сервер записал
  beacon: (p: NotePayload) => boolean; // закрытие вкладки: true = браузер принял в очередь отправки
  store: { get(k: string): string | null; set(k: string, v: string): void; del(k: string): void };
  now: () => number;
  newId: () => string;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (t: unknown) => void;
  onState: (s: SaveState) => void;
}

export const NOTE_DEBOUNCE_MS = 1000;
export const NOTE_MAX = 2000;

export function draftKey(itemId: number, generationKey: string): string {
  return `mesh-check-note:${itemId}:${generationKey}`;
}

export interface NoteSaver {
  input(text: string): void;
  flush(): Promise<void>;
  closing(): void;
  pending(): boolean;
}

export interface NoteTarget {
  itemId: number;
  generationKey: string;
  reviewer: string;
  editorId: string;
}

export function createNoteSaver(item: NoteTarget, d: NoteSaverDeps, start?: { seq: number; opId: string; body: string } | null): NoteSaver {
  const key = draftKey(item.itemId, item.generationKey);
  let seq = start?.seq ?? 0;
  let opId = start?.opId ?? "";
  let text: string | null = start ? start.body : null; // версия, ещё не подтверждённая сервером (черновик — дослать)
  let timer: unknown = null;

  const next = () => {
    seq = Math.max(d.now(), seq + 1);
    opId = d.newId();
  };
  const payload = (): NotePayload => ({ ...item, body: text ?? "", seq, opId });

  async function flush(): Promise<void> {
    if (timer !== null) d.clearTimer(timer);
    timer = null;
    if (text === null) return;
    const p = payload();
    d.onState("saving");
    const ok = await d.send(p).catch(() => false);
    if (p.seq !== seq) return; // пока шёл запрос, набрали дальше — состояние покажет следующая версия
    if (ok) {
      text = null;
      d.store.del(key);
      d.onState("saved");
    } else {
      d.onState("error"); // черновик остался в браузере — следующий ввод, уход из поля или перезагрузка дошлют
    }
  }

  return {
    input(t: string) {
      text = t.slice(0, NOTE_MAX);
      next();
      d.store.set(key, JSON.stringify({ body: text, seq, opId }));
      if (timer !== null) d.clearTimer(timer);
      timer = d.setTimer(() => void flush(), NOTE_DEBOUNCE_MS);
      d.onState("saving");
    },
    flush,
    closing() {
      if (timer !== null) d.clearTimer(timer);
      timer = null;
      if (text !== null) d.beacon(payload()); // черновик в браузере не трогаем: подтверждения от маяка нет
    },
    pending: () => text !== null,
  };
}

/** Черновик из браузера, которого сервер ещё не видел (его версия новее серверной) — показать и дослать. */
export function restoreDraft(
  store: NoteSaverDeps["store"],
  item: { itemId: number; generationKey: string },
  serverSeq: number | null,
): { body: string; seq: number; opId: string } | null {
  const raw = store.get(draftKey(item.itemId, item.generationKey));
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as { body?: unknown; seq?: unknown; opId?: unknown };
    if (typeof v.body !== "string" || typeof v.seq !== "number" || typeof v.opId !== "string") return null;
    return serverSeq !== null && v.seq <= serverSeq ? null : { body: v.body, seq: v.seq, opId: v.opId };
  } catch {
    return null;
  }
}
