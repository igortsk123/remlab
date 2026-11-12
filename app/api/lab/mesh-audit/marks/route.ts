import { NextResponse } from "next/server";
import { originOk, reviewerOk } from "@/lib/mesh-review/auth";
import { PressBody } from "@/lib/mesh-audit/check-body";
import { pressMark } from "@/lib/mesh-audit/repo-marks";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// POST — нажатие «ок»/«брак» на /lab/mesh-check (T-20261112-118): одна транзакция, идемпотентно по idem_key; не применённое
// нажатие (модель заменена, другая вкладка успела раньше) — 409 с текущей карточкой, строка журнала всё равно пишется.
export async function POST(req: Request): Promise<Response> {
  if (!(await reviewerOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  if (!(await originOk())) return NextResponse.json({ error: "bad origin" }, { status: 403 });
  const parsed = PressBody.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });
  try {
    const r = await pressMark(parsed.data);
    return NextResponse.json(r.body, { status: r.http });
  } catch (e) {
    // уникальность (sku, manual_attempt_no): две вкладки одновременно забраковали — вторая откатилась целиком
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.includes("mesh_audit_decisions_sku_attempt_uq") || msg.includes("mesh_audit_marks_idem_uq")) {
      return NextResponse.json({ error: "уже нажато в другой вкладке, обновите страницу", code: "race" }, { status: 409 });
    }
    throw e;
  }
}
