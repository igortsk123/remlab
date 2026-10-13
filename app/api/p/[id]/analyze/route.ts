// Разбор фото на объекты (этап 1 интерактивного флоу). Вызывается с экрана /select на монтировании.
// Возвращает объекты для показа пользователю. Не создаёт «генерацию» (без trace-номера).

import { NextResponse } from "next/server";
import { runAnalyze } from "@/modules/generation-job";
import { captureError } from "@/lib/analytics";
import { guard } from "@/lib/ratelimit/http";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const limited = await guard(req, "generate"); // платно: разбор фото ИИ (план b2b-01)
  if (limited) return limited;
  const { id } = await ctx.params;
  try {
    const analysis = await runAnalyze(id);
    if (!analysis) return NextResponse.json({ ok: false }, { status: 404 });
    return NextResponse.json({ ok: true, analysis });
  } catch (e) {
    await captureError(e, { where: "analyze", projectId: id });
    return NextResponse.json({ ok: false }, { status: 500 });
  }
}
