import { NextResponse } from "next/server";

import { TOKEN_RE } from "@/lib/token";
import { guard } from "@/lib/ratelimit/http";
import { publicCard } from "@/modules/sends/service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Карточка ссылки для страницы покупателя (план b2b-02): квартира, язык и контакты менеджера.
// Неизвестная, отозванная и кривая ссылка неразличимы — 404.
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const limited = await guard(req, "sendRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  const card = TOKEN_RE.test(id) ? await publicCard(id) : null;
  if (!card) return NextResponse.json({ ok: false }, { status: 404 });
  return NextResponse.json({ ok: true, card }, { headers: { "Cache-Control": "no-store" } });
}
