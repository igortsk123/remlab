import { NextResponse } from "next/server";
import { z } from "zod";
import { machineOk, originOk, reviewerOk } from "@/lib/mesh-review/auth";
import { cancel, decide, listDecisions } from "@/lib/mesh-audit/repo-decisions";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const DecisionBody = z.object({
  itemId: z.number().int().positive(),
  generationKey: z.string().min(1),
  verdict: z.enum(["redo", "replace_needed"]),
  idemKey: z.string().min(1).max(300),
});

// POST — клик владельца: одна транзакция, идемпотентно по idem_key, 409 для устаревшей вкладки.
export async function POST(req: Request): Promise<Response> {
  if (!(await reviewerOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  if (!(await originOk())) return NextResponse.json({ error: "bad origin" }, { status: 403 });
  const parsed = DecisionBody.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });
  const b = parsed.data;
  try {
    const r = await decide(b.itemId, b.generationKey, b.verdict, b.idemKey);
    return NextResponse.json(r.body, { status: r.http });
  } catch (e) {
    // уникальность (sku, manual_attempt_no): две вкладки одновременно — вторая получает 409
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.includes("mesh_audit_decisions_sku_attempt_uq")) {
      return NextResponse.json({ error: "решение уже принято в другой вкладке — обновите страницу", code: "race" }, { status: 409 });
    }
    throw e;
  }
}

// DELETE — владелец отменяет случайный клик (пока переделка не ушла в очередь).
export async function DELETE(req: Request): Promise<Response> {
  if (!(await reviewerOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  if (!(await originOk())) return NextResponse.json({ error: "bad origin" }, { status: 403 });
  const parsed = z
    .object({ itemId: z.number().int().positive(), generationKey: z.string().min(1) })
    .safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });
  const r = await cancel(parsed.data.itemId, parsed.data.generationKey);
  return NextResponse.json(r.body, { status: r.http });
}

// GET ?after_id=N — конвейер забирает решения курсором.
export async function GET(req: Request): Promise<Response> {
  if (!(await machineOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  const after = Number(new URL(req.url).searchParams.get("after_id") ?? "0");
  const decisions = await listDecisions(Number.isFinite(after) ? after : 0);
  return NextResponse.json({ decisions });
}
