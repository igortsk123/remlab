import { NextResponse } from "next/server";

import { collectionRenameIn, collectionShotIn, type CollectionOut } from "@/contracts/collection";
import { foreignOrigin } from "@/lib/http/origin";
import { currentPrices, priceIndex } from "@/lib/collections/prices";
import { loadDemoRaw } from "@/lib/partners/demo-data";
import { findApartment } from "@/lib/partners/registry";
import { guard } from "@/lib/ratelimit/http";
import { TOKEN_RE } from "@/lib/token";
import { collectionRepo, editHashOf } from "@/modules/collections/repository";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Открыть коллекцию по ссылке (план b2b-05): снимок + ТЕКУЩИЕ цены из витрины этой квартиры;
// товара в витрине нет — помечен `unavailable`, цена из снимка как текущая не показывается.
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const limited = await guard(req, "sendRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  const row = TOKEN_RE.test(id) ? await collectionRepo().get(id) : null;
  if (!row) return NextResponse.json({ ok: false }, { status: 404 });
  const src = findApartment(row.payload.apartmentId)?.apartment.sources.demoData;
  const idx = src ? priceIndex(await loadDemoRaw(src)) : null;
  const sids = [...row.payload.items, ...row.payload.decor].map((i) => i.sku?.sid).filter((x): x is string => !!x);
  const { editHash: _secret, ...pub } = row.payload;      // хеш секрета редактирования наружу не уходит
  const out: CollectionOut = { ...pub, id: row.id, partnerId: row.partnerId, createdAt: row.createdAt.toISOString(),
    expiresAt: new Date(row.createdAt.getTime() + 365 * 86_400_000).toISOString(),
    current: currentPrices([...new Set(sids)], idx && idx.size ? idx : null) };
  return NextResponse.json({ ok: true, collection: out }, { headers: { "Cache-Control": "no-store" } });
}

// Прикрепить картинку к только что сохранённой коллекции (план demo-03, 2.13): страница снимает бесплатный черновой
// кадр в фоне после сохранения. Только наш путь кадра, один раз, в первые 30 минут — дальше коллекция неизменна.
export async function PATCH(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const limited = await guard(req, "collectionSave");
  if (limited) return limited;
  if (foreignOrigin(req)) return new Response(null, { status: 403 });
  const { id } = await ctx.params;
  if (!TOKEN_RE.test(id)) return NextResponse.json({ ok: false }, { status: 404 });
  // тело — крошечное (кадр или имя): заявленный размер больше — отказ ДО чтения (Codex 18.10: `slice` после `text()` не ограничивал)
  if (Number(req.headers.get("content-length") ?? 0) > 2048) return NextResponse.json({ ok: false, error: "too_large" }, { status: 413 });
  let body: unknown = null;
  try { body = JSON.parse((await req.text()).slice(0, 1024)); } catch { /* разбор ниже вернёт 400 */ }
  // ПЕРЕИМЕНОВАНИЕ (demo-15): имя + секрет редактирования; неверный секрет или коллекция без секрета — 403
  const rn = collectionRenameIn.safeParse(body);
  if (rn.success) {
    const ok = await collectionRepo().rename(id, rn.data.displayName, editHashOf(rn.data.editToken));
    return NextResponse.json({ ok }, { status: ok ? 200 : 403 });
  }
  const parsed = collectionShotIn.safeParse(body);
  if (!parsed.success) return NextResponse.json({ ok: false, error: "bad_request" }, { status: 400 });
  const ok = await collectionRepo().setShot(id, parsed.data.shot, new Date(), parsed.data.stateId);
  return NextResponse.json({ ok }, { status: ok ? 200 : 409 });
}
