import { NextResponse } from "next/server";

import { lang as langSchema } from "@/contracts/partner";
import { guard } from "@/lib/ratelimit/http";
import { apartmentCard, demoProfile, findApartment } from "@/lib/partners/registry";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Карточка квартиры для шапки витрины и 3D (план b2b-06): тип, площадь, ЖК, срок сдачи, этаж,
// цена и сертификат — всё посчитано здесь, страницы только рисуют. `?lang=` меняет только язык.
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const limited = await guard(req, "sendRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  const hit = findApartment(id);
  if (!hit) return NextResponse.json({ ok: false }, { status: 404 });
  const q = new URL(req.url).searchParams;
  const l = langSchema.safeParse(q.get("lang"));
  // анонимное демо (`demo=1`, страница не по ссылке менеджера и не встроенная): EN — британский двойник (ADR-0298)
  const shown = l.success && q.get("demo") === "1" ? demoProfile(hit, l.data) : hit;
  return NextResponse.json({ ok: true, card: apartmentCard(shown, l.success ? l.data : undefined) }, { headers: { "Cache-Control": "public, max-age=300" } });
}
