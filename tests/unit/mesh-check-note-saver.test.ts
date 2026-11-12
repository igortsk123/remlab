import { beforeEach, describe, expect, it, vi } from "vitest";
import { createNoteSaver, draftKey, NOTE_DEBOUNCE_MS, restoreDraft, type NotePayload, type NoteSaverDeps, type SaveState } from "@/lib/mesh-audit/note-saver";

// Комментарий /lab/mesh-check сохраняется сам (T-20261112-118): через 1 с после ввода, при уходе из поля, маяком при закрытии
// вкладки; до ответа сервера версия лежит в браузере. Таймеры — поддельные (vi.useFakeTimers), сеть — заглушка.

const target = { itemId: 7, generationKey: "g1", reviewer: "Аня", editorId: "ed-1" };

function setup(sendImpl?: (p: NotePayload) => Promise<boolean>) {
  const mem = new Map<string, string>();
  const sent: NotePayload[] = [];
  const beacons: NotePayload[] = [];
  const states: SaveState[] = [];
  let clock = 1_800_000_000_000;
  let ids = 0;
  const d: NoteSaverDeps = {
    send: vi.fn(async (p: NotePayload) => {
      sent.push(p);
      return sendImpl ? sendImpl(p) : true;
    }),
    beacon: (p) => {
      beacons.push(p);
      return true;
    },
    store: { get: (k) => mem.get(k) ?? null, set: (k, v) => void mem.set(k, v), del: (k) => void mem.delete(k) },
    now: () => clock,
    newId: () => `op-${++ids}`,
    setTimer: (fn, ms) => setTimeout(fn, ms),
    clearTimer: (t) => clearTimeout(t as ReturnType<typeof setTimeout>),
    onState: (s) => states.push(s),
  };
  return { d, mem, sent, beacons, states, tick: (ms: number) => (clock += ms) };
}

describe("mesh-check: сохранение комментария", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("через 1 с после последней буквы уходит одна версия — последняя", async () => {
    const t = setup();
    const s = createNoteSaver(target, t.d);
    s.input("н");
    s.input("но");
    s.input("ножки");
    await vi.advanceTimersByTimeAsync(NOTE_DEBOUNCE_MS - 1);
    expect(t.sent).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(t.sent.map((p) => p.body)).toEqual(["ножки"]);
    expect(t.states.at(-1)).toBe("saved");
    expect(t.mem.has(draftKey(7, "g1"))).toBe(false); // подтверждено сервером — черновик убран
  });

  it("уход из поля сохраняет сразу, без ожидания", async () => {
    const t = setup();
    const s = createNoteSaver(target, t.d);
    s.input("цвет не тот");
    await s.flush();
    expect(t.sent).toHaveLength(1);
    expect(s.pending()).toBe(false);
  });

  it("номер версии растёт даже в одну миллисекунду, у каждой версии свой opId", () => {
    const t = setup();
    const s = createNoteSaver(target, t.d);
    s.input("а");
    s.closing();
    s.input("аб");
    s.closing();
    const [a, b] = t.beacons;
    expect(b!.seq).toBeGreaterThan(a!.seq);
    expect(b!.opId).not.toBe(a!.opId);
  });

  it("закрытие вкладки посреди ввода — маяк с той же версией, черновик в браузере остаётся до подтверждения", () => {
    const t = setup();
    const s = createNoteSaver(target, t.d);
    s.input("ножки пропали");
    s.closing();
    expect(t.beacons.map((p) => p.body)).toEqual(["ножки пропали"]);
    expect(t.sent).toHaveLength(0); // таймер снят: второй отправки той же версии нет
    expect(restoreDraft(t.d.store, target, null)).toMatchObject({ body: "ножки пропали", opId: t.beacons[0]!.opId });
  });

  it("нет связи — ошибка, черновик цел; повтор той же версии уходит с тем же opId (без второй строки журнала)", async () => {
    let ok = false;
    const t = setup(async () => ok);
    const s = createNoteSaver(target, t.d);
    s.input("фото другое");
    await s.flush();
    expect(t.states.at(-1)).toBe("error");
    expect(s.pending()).toBe(true);
    ok = true;
    await s.flush();
    expect(t.sent).toHaveLength(2);
    expect(t.sent[0]!.opId).toBe(t.sent[1]!.opId);
    expect(t.states.at(-1)).toBe("saved");
  });

  it("поздний ответ старой версии не рисует «сохранено», пока набирают дальше", async () => {
    let release: (v: boolean) => void = () => undefined;
    const t = setup(() => new Promise<boolean>((r) => (release = r)));
    const s = createNoteSaver(target, t.d);
    s.input("раз");
    const f = s.flush();
    s.input("раз два");
    release(true);
    await f;
    expect(t.states.at(-1)).toBe("saving");
    expect(s.pending()).toBe(true);
  });

  it("после перезагрузки черновик новее серверной версии досылается той же версией; старый — нет", async () => {
    const t = setup();
    t.mem.set(draftKey(7, "g1"), JSON.stringify({ body: "черновик", seq: 500, opId: "op-old" }));
    expect(restoreDraft(t.d.store, target, 500)).toBeNull();
    const draft = restoreDraft(t.d.store, target, 400);
    expect(draft).toEqual({ body: "черновик", seq: 500, opId: "op-old" });
    const s = createNoteSaver(target, t.d, draft);
    await s.flush();
    expect(t.sent[0]).toMatchObject({ body: "черновик", seq: 500, opId: "op-old" });
  });

  it("испорченный черновик игнорируется", () => {
    const t = setup();
    t.mem.set(draftKey(7, "g1"), "{не json");
    expect(restoreDraft(t.d.store, target, null)).toBeNull();
    t.mem.set(draftKey(7, "g1"), JSON.stringify({ body: "x", seq: 1 }));
    expect(restoreDraft(t.d.store, target, null)).toBeNull();
  });
});
