import { beforeEach, describe, expect, it, vi } from "vitest";

// Ручки /lab/mesh-check (T-20261112-118): вход, разбор тела (в т.ч. маяк — JSON-Blob), гонка двух вкладок. Слой БД подменён:
// в тестах проекта нет Postgres (DATABASE_URL нет); транзакции — `repo-marks.ts` / `repo-notes.ts`.

const auth = vi.hoisted(() => ({ reviewer: true, origin: true }));
const repo = vi.hoisted(() => ({ pressMark: vi.fn(), saveNote: vi.fn() }));

vi.mock("@/lib/mesh-review/auth", () => ({ reviewerOk: async () => auth.reviewer, originOk: async () => auth.origin }));
vi.mock("@/lib/mesh-audit/repo-marks", () => ({ pressMark: repo.pressMark }));
vi.mock("@/lib/mesh-audit/repo-notes", () => ({ saveNote: repo.saveNote }));

import { POST as postMark } from "@/app/api/lab/mesh-audit/marks/route";
import { POST as postNote } from "@/app/api/lab/mesh-audit/notes/route";

const press = { itemId: 3, generationKey: "g1", press: "bad", expected: null, reviewer: "Аня", idemKey: "k-12345678" };
const note = { itemId: 3, generationKey: "g1", body: "ножки", seq: 1_800_000_000_001, opId: "op-12345678", editorId: "ed-12345678", reviewer: "Аня" };
const req = (url: string, body: BodyInit) => new Request(`http://app${url}`, { method: "POST", body, headers: { "content-type": "application/json" } });

beforeEach(() => {
  auth.reviewer = true;
  auth.origin = true;
  repo.pressMark.mockReset();
  repo.saveNote.mockReset();
});

describe("POST /api/lab/mesh-audit/marks", () => {
  it("без входа — 401, чужой сайт — 403, в БД ничего не уходит", async () => {
    auth.reviewer = false;
    expect((await postMark(req("/m", JSON.stringify(press)))).status).toBe(401);
    auth.reviewer = true;
    auth.origin = false;
    expect((await postMark(req("/m", JSON.stringify(press)))).status).toBe(403);
    expect(repo.pressMark).not.toHaveBeenCalled();
  });
  it("кривое тело — 400", async () => {
    expect((await postMark(req("/m", "{"))).status).toBe(400);
    expect((await postMark(req("/m", JSON.stringify({ ...press, press: "maybe" })))).status).toBe(400);
  });
  it("нажатие уходит в одну транзакцию слоя БД как есть; ответ слоя — ответ ручки", async () => {
    repo.pressMark.mockResolvedValue({ http: 200, body: { ok: true, item: { id: 3 }, reason: "queued_kept" } });
    const r = await postMark(req("/m", JSON.stringify(press)));
    expect(r.status).toBe(200);
    expect(await r.json()).toMatchObject({ reason: "queued_kept" });
    expect(repo.pressMark).toHaveBeenCalledWith(press);
  });
  it("две вкладки одновременно забраковали — вторая получает понятный 409, а не 500", async () => {
    repo.pressMark.mockRejectedValue(new Error('duplicate key value violates unique constraint "mesh_audit_decisions_sku_attempt_uq"'));
    const r = await postMark(req("/m", JSON.stringify(press)));
    expect(r.status).toBe(409);
    expect(await r.json()).toMatchObject({ code: "race" });
  });
});

describe("POST /api/lab/mesh-audit/notes", () => {
  it("маяк закрытия вкладки (тело — Blob) разбирается так же, как обычный запрос", async () => {
    repo.saveNote.mockResolvedValue({ http: 200, body: { ok: true, applied: true } });
    const blob = new Blob([JSON.stringify(note)], { type: "application/json" });
    const r = await postNote(new Request("http://app/n", { method: "POST", body: blob }));
    expect(r.status).toBe(200);
    expect(repo.saveNote).toHaveBeenCalledWith(note);
  });
  it("без входа — 401; кривое тело — 400", async () => {
    auth.reviewer = false;
    expect((await postNote(req("/n", JSON.stringify(note)))).status).toBe(401);
    auth.reviewer = true;
    expect((await postNote(req("/n", "мусор"))).status).toBe(400);
    expect(repo.saveNote).not.toHaveBeenCalled();
  });
  it("тот же пакет двумя путями одновременно (запрос и маяк) — второй не ошибка", async () => {
    repo.saveNote.mockRejectedValue(new Error('duplicate key value violates unique constraint "mesh_audit_notes_op_uq"'));
    const r = await postNote(req("/n", JSON.stringify(note)));
    expect(r.status).toBe(200);
    expect(await r.json()).toMatchObject({ duplicate: true });
  });
});
