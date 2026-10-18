import { NextResponse } from "next/server";

import { isLiveCheck } from "@/lib/http/live-check";
import { foreignOrigin } from "@/lib/http/origin";

import { pageEventIn } from "@/contracts/analytics";
import { guard } from "@/lib/ratelimit/http";
import { findApartment } from "@/lib/partners/registry";
import { reportRepo } from "@/modules/partner-report/repository";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Календарный день YYYY-MM-DD в поясе застройщика. */
const dayIn = (d: Date, tz: string) => new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);

// Анонимный счётчик страницы БЕЗ ссылки менеджера (план b2b-03, ADR-0265): +1 к дню × квартире × действию.
// Квартира — только из реестра; застройщик — из реестра, не от клиента. Ответ всегда пустой 204.
export async function POST(req: Request): Promise<Response> {
  const limited = await guard(req, "pageEvent");
  if (limited) return limited;
  if (foreignOrigin(req)) return new Response(null, { status: 403 }); // чужой сайт — не пишем (b2b-07)
  const raw = await req.text();
  if (raw.length > 2048) return new NextResponse(null, { status: 413 });
  let body: unknown = null;
  try { body = JSON.parse(raw); } catch { /* разбор ниже вернёт 400 */ }
  const parsed = pageEventIn.safeParse(body);
  if (!parsed.success) return new NextResponse(null, { status: 400 });
  const hit = findApartment(parsed.data.apartmentId);
  if (!hit) return new NextResponse(null, { status: 400 });
  if (isLiveCheck(req.headers)) return new NextResponse(null, { status: 204 }); // живая проверка — тот же ответ, без записи
  try {
    await reportRepo().bump({
      day: dayIn(new Date(), hit.partner.timezone), partnerId: hit.partner.id,
      apartmentId: hit.apartment.id, kind: parsed.data.kind, lang: parsed.data.lang,
    });
  } catch {
    // счётчик не должен ломать страницу покупателя
  }
  return new NextResponse(null, { status: 204 });
}
