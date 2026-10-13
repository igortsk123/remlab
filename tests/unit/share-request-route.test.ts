import { afterEach, describe, expect, it } from "vitest";

import { POST } from "@/app/api/internal/share-request/route";

// Внутренний приём заявки «отправить себе» (план b2b-01): без общего секрета — закрыто,
// с секретом — контакт уходит в хранилище (в тестах — память процесса, DATABASE_URL нет).

const body = { shareId: "a1b2c3d4e5", shareUrl: "https://remont-lab.online/test/share/a1b2c3d4e5/", channel: "telegram", contact: "@buyer", shotCount: 3, ip: "1.2.3.4" };
const req = (headers: Record<string, string>, b: unknown = body) =>
  new Request("http://app/api/internal/share-request", { method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify(b) });

describe("POST /api/internal/share-request", () => {
  const prev = process.env.INTERNAL_API_TOKEN;
  afterEach(() => {
    if (prev === undefined) delete process.env.INTERNAL_API_TOKEN;
    else process.env.INTERNAL_API_TOKEN = prev;
  });

  it("секрет не задан на сервере — 403 даже с любым заголовком", async () => {
    delete process.env.INTERNAL_API_TOKEN;
    expect((await POST(req({ "x-internal-token": "" }))).status).toBe(403);
  });

  it("неверный секрет — 403, верный — 200 и id заявки", async () => {
    process.env.INTERNAL_API_TOKEN = "tok";
    expect((await POST(req({ "x-internal-token": "nope" }))).status).toBe(403);
    const ok = await POST(req({ "x-internal-token": "tok" }));
    expect(ok.status).toBe(200);
    expect(await ok.json()).toMatchObject({ ok: true });
  });

  it("мусорный id подборки — 400", async () => {
    process.env.INTERNAL_API_TOKEN = "tok";
    expect((await POST(req({ "x-internal-token": "tok" }, { ...body, shareId: "../../etc" }))).status).toBe(400);
  });
});
