import { describe, expect, it } from "vitest";

import { trialClaimIn, trialRebuildFailCode } from "@/contracts/trial";
import { trialRebuildPublishIn, trialReparseIn } from "@/contracts/trial-bundle";

// «Перечитать планировку» (план trial-reparse-01; T-20261111-02): формы входа без базы. Поведение очереди — `_trial-reparse-db.ts`.
const ID = "A".repeat(22);
const lease = { id: "rb1", attempt: 1, leaseToken: "t".repeat(43), jobId: ID, bundle: "{}", sha256: "a".repeat(64) };
const room = { panel: "p0", from: "r1", to: "r2", anchor: { x: 0.5, y: 0.5 } };
const op = { panel: "p0", key: "s3", to: "s1", srcIdx: 1, srcC: [10, 20], c: [12, 20] };

describe("контракты «перечитать планировку»", () => {
  it("постановка: id тура и request_id в формате очереди", () => {
    expect(trialReparseIn.safeParse({ jobId: ID, requestId: "reparse-0001" }).success).toBe(true);
    for (const bad of [{ jobId: "short", requestId: "reparse-0001" }, { jobId: ID, requestId: "x" }, { jobId: ID }, { jobId: ID, requestId: "a b c d e f" }]) {
      expect(trialReparseIn.safeParse(bad).success).toBe(false);
    }
  });

  it("карта публикации: ключи проёмов s<номер>/u<токен>; снятые комнаты и правки ограничены", () => {
    const ok = (reparse: unknown) => trialRebuildPublishIn.safeParse({ ...lease, reparse }).success;
    expect(ok({ released: ["living"], rooms: [room], openings: [op, { ...op, key: "uAbc_123", to: "uAbc_123", srcIdx: null, srcC: null }] })).toBe(true);
    expect(ok({ released: [], rooms: [], openings: [{ ...op, to: "x1" }] })).toBe(false);
    expect(ok({ released: [], rooms: [], openings: [{ ...op, key: "s1000" }] })).toBe(false);
    expect(ok({ released: Array.from({ length: 41 }, (_, i) => `bedroom-${i}`), rooms: [], openings: [] })).toBe(false);
    expect(ok({ released: [], rooms: [{ ...room, anchor: { x: "a", y: 0 } }], openings: [] })).toBe(false);
    expect(trialRebuildPublishIn.safeParse(lease).success).toBe(true); // без карты — как раньше
  });

  it("claim: навык reparse необязателен; коды отказа сторожа и кэша — в общем списке", () => {
    expect(trialClaimIn.safeParse({ workerId: "w1" }).success).toBe(true);
    expect(trialClaimIn.safeParse({ workerId: "w1", rebuilds: true, edit: true, reparse: true }).success).toBe(true);
    for (const c of ["cache_miss", "edits_conflict", "regress"]) expect(trialRebuildFailCode.safeParse(c).success).toBe(true);
  });
});
