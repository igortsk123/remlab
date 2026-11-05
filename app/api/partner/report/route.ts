import { NextResponse } from "next/server";

import { TOKEN_RE } from "@/lib/token";
import { guard } from "@/lib/ratelimit/http";
import { loadDemoRaw, showcaseStyles } from "@/lib/partners/demo-data";
import { findPartner } from "@/lib/partners/registry";
import { quizPart } from "@/modules/partner-report/quiz";
import { buildReport, firstWeek } from "@/modules/partner-report/report";
import { reportRepo } from "@/modules/partner-report/repository";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const WEEKS = 12;

// Отчёт застройщику (план b2b-03, ADR-0265): ключ — заголовком `x-partner-key` (на странице он живёт во
// #фрагменте адреса). Застройщик — ТОЛЬКО из ключа; все выборки фильтруются им.
export async function GET(req: Request): Promise<Response> {
  const limited = await guard(req, "partnerReport");
  if (limited) return limited;
  const key = req.headers.get("x-partner-key") ?? "";
  const partnerId = TOKEN_RE.test(key) ? await reportRepo().partnerByKey(key) : null;
  const p = partnerId ? findPartner(partnerId) : null;
  if (!p) return NextResponse.json({ ok: false }, { status: 403, headers: { "Cache-Control": "no-store" } });
  const now = new Date();
  // ровно WEEKS недель по поясу застройщика; из базы берём с запасом в сутки, лишнее отсекает buildReport
  const fromWeek = firstWeek(now, p.timezone, WEEKS);
  const since = new Date(new Date(`${fromWeek}T00:00:00Z`).getTime() - 86_400_000);
  const rows = await reportRepo().rows(p.id, since, since.toISOString().slice(0, 10));
  // порядок стилей блока «Знакомство» — по витрине квартиры; витрину грузим, только если опрос что-то насчитал
  const quizApts = new Set(rows.counters.filter((c) => quizPart(c.kind)).map((c) => c.apartmentId));
  const showcase = Object.fromEntries(await Promise.all(p.apartments.filter((a) => quizApts.has(a.id) && a.sources.demoData)
    .map(async (a) => [a.id, showcaseStyles(await loadDemoRaw(a.sources.demoData!))] as const)));
  const report = buildReport({ ...rows, timezone: p.timezone, now, fromWeek, showcase });
  const apartments = Object.fromEntries(p.apartments.map((a) => [a.id, a.number ? `кв. ${a.number}` : a.id]));
  return NextResponse.json(
    { ok: true, partner: { id: p.id, name: p.nameRu }, timezone: p.timezone, periodWeeks: WEEKS, apartments, ...report, generatedAt: now.toISOString() },
    { headers: { "Cache-Control": "no-store" } },
  );
}
