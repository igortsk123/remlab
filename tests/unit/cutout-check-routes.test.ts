import { beforeEach, describe, expect, it, vi } from "vitest";

// Ручки /api/lab/cutout-check (T-20261119-104): входы (кука владельца / Bearer конвейера), разбор тела, ответы слоя БД. Слой БД подменён.

const auth = vi.hoisted(() => ({ reviewer: true, origin: true, machine: true }));
const repo = vi.hoisted(() => ({ pressMark: vi.fn(), saveNote: vi.fn(), upsertItems: vi.fn(), exportMarks: vi.fn() }));

vi.mock("@/lib/mesh-review/auth", () => ({ reviewerOk: async () => auth.reviewer, originOk: async () => auth.origin, machineOk: async () => auth.machine }));
vi.mock("@/lib/cutout-check/repo-marks", () => ({ pressMark: repo.pressMark, saveNote: repo.saveNote }));
vi.mock("@/lib/cutout-check/repo-items", () => ({ upsertItems: repo.upsertItems }));
vi.mock("@/lib/cutout-check/repo-export", () => ({ exportMarks: repo.exportMarks }));

import { GET as getExport } from "@/app/api/lab/cutout-check/export/route";
import { POST as postItems } from "@/app/api/lab/cutout-check/items/route";
import { POST as postMark } from "@/app/api/lab/cutout-check/marks/route";
import { POST as postNote } from "@/app/api/lab/cutout-check/notes/route";

const press = { itemId: 3, generationKey: "g1", press: "bad", expected: null, reviewer: "Аня", idemKey: "k-12345678" };
const note = { itemId: 3, generationKey: "g1", body: "дыра у ножки", seq: 1_800_000_000_001, opId: "op-12345678", editorId: "ed-12345678", reviewer: "Аня" };
const post = (url: string, body: BodyInit) => new Request(`http://app${url}`, { method: "POST", body, headers: { "content-type": "application/json" } });

beforeEach(() => {
  auth.reviewer = true;
  auth.origin = true;
  auth.machine = true;
  for (const f of Object.values(repo)) f.mockReset();
});

describe("POST marks", () => {
  it("без входа — 401, чужой сайт — 403, в БД ничего не уходит", async () => {
    auth.reviewer = false;
    expect((await postMark(post("/m", JSON.stringify(press)))).status).toBe(401);
    auth.reviewer = true;
    auth.origin = false;
    expect((await postMark(post("/m", JSON.stringify(press)))).status).toBe(403);
    expect(repo.pressMark).not.toHaveBeenCalled();
  });
  it("кривое тело — 400; верное уходит в слой БД как есть, ответ слоя — ответ ручки", async () => {
    expect((await postMark(post("/m", "{"))).status).toBe(400);
    expect((await postMark(post("/m", JSON.stringify({ ...press, press: "maybe" })))).status).toBe(400);
    repo.pressMark.mockResolvedValue({ http: 409, body: { error: "x", code: "state_conflict" } });
    const r = await postMark(post("/m", JSON.stringify(press)));
    expect(r.status).toBe(409);
    expect(repo.pressMark).toHaveBeenCalledWith(press);
  });
  it("гонка по idem_key (уникальный ключ) — 409 race, не 500", async () => {
    repo.pressMark.mockRejectedValue(new Error('duplicate key value violates unique constraint "cutout_check_marks_op_uq"'));
    const r = await postMark(post("/m", JSON.stringify(press)));
    expect(r.status).toBe(409);
    expect(await r.json()).toMatchObject({ code: "race" });
  });
});

describe("POST notes", () => {
  it("маяк (тело — JSON-Blob текстом) принимается; без входа — 401; кривое — 400", async () => {
    repo.saveNote.mockResolvedValue({ http: 200, body: { ok: true, applied: true } });
    expect((await postNote(post("/n", JSON.stringify(note)))).status).toBe(200);
    expect(repo.saveNote).toHaveBeenCalledWith(note);
    expect((await postNote(post("/n", "не json"))).status).toBe(400);
    auth.reviewer = false;
    expect((await postNote(post("/n", JSON.stringify(note)))).status).toBe(401);
  });
  it("тот же op_id двумя путями сразу — ok, без второй строки", async () => {
    repo.saveNote.mockRejectedValue(new Error('violates unique constraint "cutout_check_marks_op_uq"'));
    const r = await postNote(post("/n", JSON.stringify(note)));
    expect(await r.json()).toMatchObject({ ok: true, duplicate: true });
  });
});

describe("POST items (DEV → сервер) и GET export", () => {
  const body = { run: "1119-a", items: [{ sku: "s_1", generationKey: "abc", position: 0 }] };
  it("заливка — только Bearer конвейера; кука владельца не годится", async () => {
    auth.machine = false;
    expect((await postItems(post("/i", JSON.stringify(body)))).status).toBe(401);
    expect(repo.upsertItems).not.toHaveBeenCalled();
    auth.machine = true;
    repo.upsertItems.mockResolvedValue(1);
    expect(await (await postItems(post("/i", JSON.stringify(body)))).json()).toEqual({ ok: true, put: 1 });
    expect(repo.upsertItems).toHaveBeenCalledWith("1119-a", body.items);
  });
  it("выгрузка: владелец или конвейер; без обоих — 401; нет карточек — 404", async () => {
    auth.reviewer = false;
    auth.machine = false;
    expect((await getExport(new Request("http://app/e"))).status).toBe(401);
    auth.machine = true;
    repo.exportMarks.mockResolvedValue(null);
    expect((await getExport(new Request("http://app/e?run=x"))).status).toBe(404);
    repo.exportMarks.mockResolvedValue({ run: "x", total: 2, ok: 1, bad: 1, journal: 3, marks: [] });
    const r = await getExport(new Request("http://app/e?run=x"));
    expect(repo.exportMarks).toHaveBeenLastCalledWith("x");
    expect(await r.json()).toMatchObject({ bad: 1, journal: 3 });
  });
});
