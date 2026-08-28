import { desc, eq, sql } from "drizzle-orm";
import { NextResponse } from "next/server";
import { z } from "zod";
import { db } from "@/lib/db";
import { meshReviewTasks } from "@/db/schema";
import { machineOk, reviewerOk } from "@/lib/mesh-review/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// GET — открытые задачи для страницы владельца (кука) ИЛИ для конвейера (Bearer).
export async function GET(): Promise<Response> {
  if (!(await reviewerOk()) && !(await machineOk())) {
    return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  }
  const rows = await db()
    .select()
    .from(meshReviewTasks)
    .where(eq(meshReviewTasks.status, "open"))
    .orderBy(desc(meshReviewTasks.id))
    .limit(60);
  return NextResponse.json({ tasks: rows });
}

const TaskIn = z.object({
  taskKey: z.string().min(1),
  sku: z.string().min(1),
  role: z.string().optional(),
  contract: z.string().min(1),
  payload: z.unknown(),
});
const TasksBody = z.object({ tasks: z.array(TaskIn).min(1).max(100) });

// POST — DEV-конвейер идемпотентно ставит задачи (upsert по task_key; supersede старой
// задачи того же SKU с другим glb_sha делает сам конвейер отдельным статусом).
export async function POST(req: Request): Promise<Response> {
  if (!(await machineOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  const parsed = TasksBody.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });
  let put = 0;
  for (const t of parsed.data.tasks) {
    await db()
      .insert(meshReviewTasks)
      .values({ taskKey: t.taskKey, sku: t.sku, role: t.role ?? null, contract: t.contract, payload: t.payload ?? {} })
      .onConflictDoUpdate({
        target: meshReviewTasks.taskKey,
        set: { payload: t.payload ?? {}, status: sql`case when ${meshReviewTasks.status}='decided' then 'decided' else 'open' end` },
      });
    put += 1;
  }
  return NextResponse.json({ ok: true, put });
}
