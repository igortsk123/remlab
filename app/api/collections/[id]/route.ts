import { NextResponse } from "next/server";

import type { CollectionOut } from "@/contracts/collection";
import { currentPrices, priceIndex } from "@/lib/collections/prices";
import { loadDemoRaw } from "@/lib/partners/demo-data";
import { findApartment } from "@/lib/partners/registry";
import { guard } from "@/lib/ratelimit/http";
import { TOKEN_RE } from "@/lib/token";
import { collectionRepo } from "@/modules/collections/repository";

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
  const out: CollectionOut = { ...row.payload, id: row.id, partnerId: row.partnerId, createdAt: row.createdAt.toISOString(),
    current: currentPrices([...new Set(sids)], idx && idx.size ? idx : null) };
  return NextResponse.json({ ok: true, collection: out }, { headers: { "Cache-Control": "no-store" } });
}
