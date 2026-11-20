import { NextResponse } from "next/server";
import { machineOk, reviewerOk } from "@/lib/mesh-review/auth";
import { exportMarks } from "@/lib/cutout-check/repo-export";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// GET ?run=<метка> — отметки владельца списком (кука владельца или Bearer конвейера): текущее состояние карточек с «не ок» / «ок» + текст,
// плюс число строк журнала. Без run — текущий прогон. Это вход для перегона цепочки вырезки (`tools/scout/cutout_check_sync.py --export`).
export async function GET(req: Request): Promise<Response> {
  if (!(await reviewerOk()) && !(await machineOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  const run = new URL(req.url).searchParams.get("run") ?? undefined;
  const data = await exportMarks(run);
  if (!data) return NextResponse.json({ error: "нет карточек" }, { status: 404 });
  return NextResponse.json(data);
}
