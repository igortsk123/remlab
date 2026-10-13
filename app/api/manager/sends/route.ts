import { NextResponse } from "next/server";
import { z } from "zod";

import { managerFromRequest } from "@/lib/manager-auth";
import { guard } from "@/lib/ratelimit/http";
import { sendUrl } from "@/modules/sends/apartments";
import { createSend } from "@/modules/sends/service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const Body = z.object({ apartmentId: z.string().min(1).max(80) });

// Новая ссылка со страницы менеджера (когда бот не подключён). Квартира — только из его партнёра.
export async function POST(req: Request): Promise<Response> {
  const limited = await guard(req, "manager");
  if (limited) return limited;
  const m = await managerFromRequest(req);
  if (!m) return NextResponse.json({ ok: false }, { status: 403 });
  const parsed = Body.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ ok: false }, { status: 400 });
  const s = await createSend(m, parsed.data.apartmentId, "page");
  if (!s) return NextResponse.json({ ok: false, error: "unknown_apartment" }, { status: 400 });
  return NextResponse.json({ ok: true, id: s.id, url: sendUrl(s.id) });
}
