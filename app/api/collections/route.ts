import { NextResponse } from "next/server";

import { collectionIn } from "@/contracts/collection";
import { guard } from "@/lib/ratelimit/http";
import { findApartment } from "@/lib/partners/registry";
import { priceIndex } from "@/lib/collections/prices";
import { loadDemoRaw } from "@/lib/partners/demo-data";
import { collectionRepo } from "@/modules/collections/repository";
import { sendStore } from "@/modules/sends/service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BYTES = 64 * 1024;

// Сохранить коллекцию (план b2b-05): снимок своей расстановки → короткая ссылка. Квартира — только из
// реестра и только с витриной; номер отправки менеджера — только существующий и не отозванный.
export async function POST(req: Request): Promise<Response> {
  const limited = await guard(req, "collectionSave");
  if (limited) return limited;
  const raw = await req.text();
  if (raw.length > MAX_BYTES) return NextResponse.json({ ok: false, error: "too_large" }, { status: 413 });
  let body: unknown = null;
  try { body = JSON.parse(raw); } catch { /* разбор ниже вернёт 400 */ }
  const parsed = collectionIn.safeParse(body);
  if (!parsed.success) return NextResponse.json({ ok: false, error: "bad_request" }, { status: 400 });
  const hit = findApartment(parsed.data.apartmentId);
  if (!hit?.apartment.sources.demoData) return NextResponse.json({ ok: false, error: "unknown_apartment" }, { status: 400 });
  if (parsed.data.sendId) {
    const s = await sendStore().getSend(parsed.data.sendId);
    if (!s || s.revoked || s.apartmentId !== parsed.data.apartmentId || s.partnerId !== hit.partner.id) {
      return NextResponse.json({ ok: false, error: "unknown_send" }, { status: 400 });
    }
  }
  // ТОВАРЫ — ТОЛЬКО ИЗ ВИТРИНЫ ЭТОЙ КВАРТИРЫ: название, ссылку, магазин, цену и упаковку подставляет сервер
  const idx = priceIndex(await loadDemoRaw(hit.apartment.sources.demoData));
  if (!idx.size) return NextResponse.json({ ok: false, error: "showcase_unavailable" }, { status: 503 });
  const canon = (sk: { sid: string } | undefined) => {
    if (!sk) return { ok: true as const, sku: undefined };
    const e = idx.get(sk.sid);
    if (!e) return { ok: false as const, sku: undefined };
    const { priceAt: _p, ...rest } = e;
    return { ok: true as const, sku: rest };
  };
  const items = parsed.data.items.map((i) => ({ i, c: canon(i.sku) }));
  const decor = parsed.data.decor.map((d) => ({ d, c: canon(d.sku) }));
  if ([...items, ...decor].some((x) => !x.c.ok)) return NextResponse.json({ ok: false, error: "unknown_product" }, { status: 400 });
  const clean = {
    ...parsed.data,
    items: items.map(({ i, c }) => ({ ...i, ...(c.sku ? { sku: c.sku } : {}) })),
    decor: decor.map(({ d, c }) => ({ ...d, sku: c.sku! })),
  };
  const row = await collectionRepo().create(hit.partner.id, clean);
  return NextResponse.json({ ok: true, id: row.id });
}
