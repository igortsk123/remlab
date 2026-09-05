import { NextResponse } from "next/server";
import { z } from "zod";
import { originOk, reviewerOk } from "@/lib/mesh-review/auth";
import { markSeen } from "@/lib/mesh-audit/repo-items";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// POST — страница открыта: карточки на ней считаются просмотренными (прогресс владельца).
export async function POST(req: Request): Promise<Response> {
  if (!(await reviewerOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  if (!(await originOk())) return NextResponse.json({ error: "bad origin" }, { status: 403 });
  const parsed = z.object({ itemIds: z.array(z.number().int().positive()).max(100) }).safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });
  return NextResponse.json({ ok: true, marked: await markSeen(parsed.data.itemIds) });
}
