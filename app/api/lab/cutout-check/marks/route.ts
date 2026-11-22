import { NextResponse } from "next/server";
import { originOk, reviewerOk } from "@/lib/mesh-review/auth";
import { PressBody } from "@/lib/cutout-check/body";
import { pressMark } from "@/lib/cutout-check/repo-marks";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// POST — нажатие «ок»/«не ок» на /lab/cutout-check (T-20261119-104): одна транзакция, идемпотентно по idem_key; не применённое
// нажатие (вырезка заменена, другая вкладка успела раньше) — 409 с текущей карточкой, строка журнала всё равно пишется.
export async function POST(req: Request): Promise<Response> {
  if (!(await reviewerOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  if (!(await originOk())) return NextResponse.json({ error: "bad origin" }, { status: 403 });
  const parsed = PressBody.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });
  try {
    const r = await pressMark(parsed.data);
    return NextResponse.json(r.body, { status: r.http });
  } catch (e) {
    // тот же idem_key пришёл дважды одновременно — вторая транзакция откатилась на уникальном ключе
    if ((e instanceof Error ? e.message : String(e)).includes("cutout_check_marks_op_uq")) {
      return NextResponse.json({ error: "уже нажато, обновите страницу", code: "race" }, { status: 409 });
    }
    throw e;
  }
}
