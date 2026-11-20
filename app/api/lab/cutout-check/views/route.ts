import { NextResponse } from "next/server";
import { originOk, reviewerOk } from "@/lib/mesh-review/auth";
import { ViewBody } from "@/lib/cutout-check/body";
import { recordView } from "@/lib/cutout-check/repo-marks";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// POST — «просмотрено» на /lab/cutout-check: карточка побыла на экране ≥ 1 с (без нажатий). Одна запись на карточку и вырезку;
// повтор, чужая (заменённая) вырезка и повтор op_id — ответ 200 без новой строки журнала.
export async function POST(req: Request): Promise<Response> {
  if (!(await reviewerOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  if (!(await originOk())) return NextResponse.json({ error: "bad origin" }, { status: 403 });
  const raw: unknown = await req.text().then((t) => JSON.parse(t) as unknown).catch(() => null);
  const parsed = ViewBody.safeParse(raw);
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });
  try {
    const r = await recordView(parsed.data);
    return NextResponse.json(r.body, { status: r.http });
  } catch (e) {
    if ((e instanceof Error ? e.message : String(e)).includes("cutout_check_marks_op_uq")) return NextResponse.json({ ok: true, recorded: false, reason: "duplicate" });
    throw e;
  }
}
