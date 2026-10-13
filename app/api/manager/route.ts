import { NextResponse } from "next/server";

import { managerFromRequest } from "@/lib/manager-auth";
import { guard } from "@/lib/ratelimit/http";
import { managerView } from "@/modules/sends/manager-view";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Данные страницы менеджера (план b2b-02): ключ — заголовком `x-manager-key`.
export async function GET(req: Request): Promise<Response> {
  const limited = await guard(req, "manager");
  if (limited) return limited;
  const m = await managerFromRequest(req);
  if (!m) return NextResponse.json({ ok: false }, { status: 403 });
  return NextResponse.json({ ok: true, ...(await managerView(m)) }, { headers: { "Cache-Control": "no-store" } });
}
