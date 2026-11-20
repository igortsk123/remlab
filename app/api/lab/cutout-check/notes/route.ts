import { NextResponse } from "next/server";
import { originOk, reviewerOk } from "@/lib/mesh-review/auth";
import { NoteBody } from "@/lib/cutout-check/body";
import { saveNote } from "@/lib/cutout-check/repo-marks";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// POST — версия «что не так» на /lab/cutout-check: обычный запрос, маяк закрытия вкладки (sendBeacon, тело — JSON-Blob) и досылка
// черновика после перезагрузки. Повтор op_id — без второй строки; старая версия журналится, текст не затирает.
export async function POST(req: Request): Promise<Response> {
  if (!(await reviewerOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  if (!(await originOk())) return NextResponse.json({ error: "bad origin" }, { status: 403 });
  const raw: unknown = await req.text().then((t) => JSON.parse(t) as unknown).catch(() => null);
  const parsed = NoteBody.safeParse(raw);
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });
  try {
    const r = await saveNote(parsed.data);
    return NextResponse.json(r.body, { status: r.http });
  } catch (e) {
    if ((e instanceof Error ? e.message : String(e)).includes("cutout_check_marks_op_uq")) return NextResponse.json({ ok: true, duplicate: true, applied: true });
    throw e;
  }
}
