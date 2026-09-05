import { NextResponse } from "next/server";
import { z } from "zod";
import { machineOk, originOk, reviewerOk } from "@/lib/mesh-review/auth";
import { batchState, reportBatch, requestBatch } from "@/lib/mesh-audit/repo-batches";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// GET — состояние партий (страница опрашивает во время заливки).
export async function GET(): Promise<Response> {
  if (!(await reviewerOk()) && !(await machineOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  return NextResponse.json(await batchState());
}

// POST — владелец просит партию N («следующая партия» / «загрузить эту партию»).
export async function POST(req: Request): Promise<Response> {
  if (!(await reviewerOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  if (!(await originOk())) return NextResponse.json({ error: "bad origin" }, { status: 403 });
  const parsed = z.object({ batch: z.number().int().positive().max(10_000) }).safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });
  const r = await requestBatch(parsed.data.batch);
  return NextResponse.json(r.body, { status: r.http });
}

const Report = z.object({
  token: z.string().min(1),
  status: z.enum(["uploading", "verifying", "active", "retiring", "removed", "failed"]).optional(),
  filesTotal: z.number().int().nonnegative().optional(),
  filesDone: z.number().int().nonnegative().optional(),
  bytesTotal: z.number().int().nonnegative().optional(),
  error: z.string().optional(),
});

// PATCH — публикатор на DEV отчитывается о прогрессе и переключении.
export async function PATCH(req: Request): Promise<Response> {
  if (!(await machineOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  const parsed = Report.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });
  const { token, ...patch } = parsed.data;
  const r = await reportBatch(token, patch);
  return NextResponse.json(r.body, { status: r.http });
}
