import { NextResponse } from "next/server";

import { TOKEN_RE } from "@/lib/token";
import { guard } from "@/lib/ratelimit/http";
import { findPartner } from "@/lib/partners/registry";
import { buildReport } from "@/modules/partner-report/report";
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
  const since = new Date(now.getTime() - (WEEKS * 7 + 7) * 86_400_000);
  const rows = await reportRepo().rows(p.id, since, since.toISOString().slice(0, 10));
  const report = buildReport({ ...rows, timezone: p.timezone, now });
  const apartments = Object.fromEntries(p.apartments.map((a) => [a.id, a.number ? `кв. ${a.number}` : a.id]));
  return NextResponse.json(
    { ok: true, partner: { id: p.id, name: p.nameRu }, timezone: p.timezone, periodWeeks: WEEKS, apartments, ...report, generatedAt: now.toISOString() },
    { headers: { "Cache-Control": "no-store" } },
  );
}
