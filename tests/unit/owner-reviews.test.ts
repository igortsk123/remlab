import { beforeEach, describe, expect, it } from "vitest";

import { GET, POST } from "@/app/api/lab/review/route";
import { MemoryReviewRepo } from "@/modules/owner-reviews/repository";

// Отметки владельца (ADR-0275): только известные виды и вердикты; курсор after отдаёт новые по порядку.
let repo: MemoryReviewRepo;
beforeEach(() => { repo = new MemoryReviewRepo(); (globalThis as unknown as { __remlabReviews?: unknown }).__remlabReviews = repo; });
const post = (b: unknown) => POST(new Request("http://x/api/lab/review", { method: "POST", body: JSON.stringify(b), headers: { "x-forwarded-for": "10.9.0.1" } }));

describe("отметки владельца", () => {
  it("принимает «подходит» по стилю с комментарием и отдаёт по курсору", async () => {
    expect((await post({ kind: "style", key: "112923_1|сканди", verdict: "yes", comment: "ножки тонкие" })).status).toBe(200);
    expect((await post({ kind: "quarantine", key: "112923_2", verdict: "accept" })).status).toBe(200);
    const r = await GET(new Request("http://x/api/lab/review?kind=style&after=0", { headers: { "x-forwarded-for": "10.9.0.2" } }));
    const j = (await r.json()) as { rows: { itemKey: string; verdict: string; comment: string }[] };
    expect(j.rows).toHaveLength(1);
    expect(j.rows[0]).toMatchObject({ itemKey: "112923_1|сканди", verdict: "yes", comment: "ножки тонкие" });
  });

  it("чужой вердикт, неизвестный вид и мусор в ключе — 400", async () => {
    expect((await post({ kind: "style", key: "a|сканди", verdict: "accept" })).status).toBe(400);
    expect((await post({ kind: "x", key: "a", verdict: "yes" })).status).toBe(400);
    expect((await post({ kind: "style", key: "<script>", verdict: "yes" })).status).toBe(400);
    expect((await post({ kind: "orient", key: "112923_3", verdict: "yes" })).status).toBe(400);
    expect((await post({ kind: "orient", key: "112923_3", verdict: "new" })).status).toBe(200);
  });

  it("комментарий к товару без отметки стиля и снятие отметки", async () => {
    expect((await post({ kind: "style_note", key: "112923_1", verdict: "note", comment: "подходит и к сканди, и к джапанди" })).status).toBe(200);
    expect((await post({ kind: "style_note", key: "112923_1", verdict: "note" })).status).toBe(200);
    expect((await post({ kind: "style_note", key: "112923_1", verdict: "yes" })).status).toBe(400);
    expect((await post({ kind: "style", key: "112923_1|универсальный", verdict: "clear" })).status).toBe(200);
    expect((await post({ kind: "style_note", key: "112923_1", verdict: "note", comment: "я".repeat(1001) })).status).toBe(400);
    const r = await GET(new Request("http://x/api/lab/review?kind=style_note&after=0", { headers: { "x-forwarded-for": "10.9.0.3" } }));
    const j = (await r.json()) as { rows: { itemKey: string; comment: string | null }[] };
    expect(j.rows.map((x) => x.comment)).toEqual(["подходит и к сканди, и к джапанди", null]);
  });
});
