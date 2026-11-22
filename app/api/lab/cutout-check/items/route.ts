import { NextResponse } from "next/server";
import { machineOk } from "@/lib/mesh-review/auth";
import { ItemsBody } from "@/lib/cutout-check/body";
import { upsertItems } from "@/lib/cutout-check/repo-items";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// POST — DEV кладёт карточки прогона вырезки (Bearer конвейера): upsert по (run, sku). Вырезка с новым generation_key сбрасывает
// отметку и текст этой карточки, журнал нажатий остаётся. Карточки по номеру порядка (position) идут на странице подряд.
export async function POST(req: Request): Promise<Response> {
  if (!(await machineOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  const parsed = ItemsBody.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });
  const put = await upsertItems(parsed.data.run, parsed.data.items);
  return NextResponse.json({ ok: true, put });
}
