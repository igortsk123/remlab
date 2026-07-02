// Разбор фото на объекты (этап 1 интерактивного флоу). Вызывается с экрана /select на монтировании.
// Возвращает объекты для показа пользователю. Не создаёт «генерацию» (без trace-номера).

import { NextResponse } from "next/server";
import { runAnalyze } from "@/modules/generation-job";
import { captureError } from "@/lib/analytics";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function POST(_req: Request, ctx: { params: Promise<{ id: string }> }) {
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
