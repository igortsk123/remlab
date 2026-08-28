import { asc, eq, gt } from "drizzle-orm";
import { NextResponse } from "next/server";
import { z } from "zod";
import { db } from "@/lib/db";
import { meshReviewDecisions, meshReviewTasks } from "@/db/schema";
import { machineOk, originOk, reviewerOk } from "@/lib/mesh-review/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const DecisionBody = z.object({
  taskId: z.number().int().positive(),
  choice: z.enum(["front_0", "front_90", "front_180", "front_270", "symmetric", "bad_up", "bad_mesh", "skip"]),
  idemKey: z.string().min(1).max(300),
});

// POST — клик владельца: append-only решение, идемпотентно по idem_key.
export async function POST(req: Request): Promise<Response> {
  if (!(await reviewerOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  if (!(await originOk())) return NextResponse.json({ error: "bad origin" }, { status: 403 });
  const parsed = DecisionBody.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });
  const body = parsed.data;
  const d = db();
  const [task] = await d.select().from(meshReviewTasks).where(eq(meshReviewTasks.id, body.taskId));
  if (!task) return NextResponse.json({ error: "нет задачи" }, { status: 404 });
  await d
    .insert(meshReviewDecisions)
    .values({ taskId: body.taskId, choice: body.choice, idemKey: body.idemKey })
    .onConflictDoNothing({ target: meshReviewDecisions.idemKey });
  // «пропустить» оставляет задачу открытой — вернётся с другим ракурсом
  if (body.choice !== "skip") {
    await d.update(meshReviewTasks).set({ status: "decided" }).where(eq(meshReviewTasks.id, body.taskId));
  }
  return NextResponse.json({ ok: true });
}

// GET ?after_id=N — DEV-конвейер забирает решения курсором; курсор двигает у себя
// только после применения (Codex q25).
export async function GET(req: Request): Promise<Response> {
  if (!(await machineOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  const after = Number(new URL(req.url).searchParams.get("after_id") ?? "0");
  const rows = await db()
    .select({
      id: meshReviewDecisions.id,
      taskId: meshReviewDecisions.taskId,
      choice: meshReviewDecisions.choice,
      reviewer: meshReviewDecisions.reviewer,
      createdAt: meshReviewDecisions.createdAt,
      taskKey: meshReviewTasks.taskKey,
      sku: meshReviewTasks.sku,
    })
    .from(meshReviewDecisions)
    .innerJoin(meshReviewTasks, eq(meshReviewDecisions.taskId, meshReviewTasks.id))
    .where(gt(meshReviewDecisions.id, Number.isFinite(after) ? after : 0))
    .orderBy(asc(meshReviewDecisions.id))
    .limit(200);
  return NextResponse.json({ decisions: rows });
}
