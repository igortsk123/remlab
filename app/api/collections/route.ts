import { NextResponse } from "next/server";

import { foreignOrigin } from "@/lib/http/origin";

import { collectionIdsIn, collectionIn } from "@/contracts/collection";
import { collectionOut, showcaseIndexes } from "@/lib/collections/read";
import { guard } from "@/lib/ratelimit/http";
import { apartmentCard, findApartment } from "@/lib/partners/registry";
import { canonDeveloperOptions } from "@/lib/partners/options";
import { priceIndex } from "@/lib/collections/prices";
import { loadDemoRaw, variantKey } from "@/lib/partners/demo-data";
import { collectionRepo, editHashOf } from "@/modules/collections/repository";
import { randomToken } from "@/lib/token";
import { sendStore } from "@/modules/sends/service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BYTES = 64 * 1024;

// Открыть коллекции пачкой (demo-19 А1): `?ids=a,b,c` — те же публичные снимки, что `GET /api/collections/[id]`, по номерам из
// ссылок этого браузера; лимит чтений — на запрос, а не на коллекцию. Несуществующих и истёкших в ответе нет — так страница
// отличает «коллекции нет» от сбоя сети.
export async function GET(req: Request): Promise<Response> {
  const limited = await guard(req, "sendRead");
  if (limited) return limited;
  const parsed = collectionIdsIn.safeParse(new URL(req.url).searchParams.get("ids") ?? "");
  if (!parsed.success) return NextResponse.json({ ok: false, error: "bad_request" }, { status: 400 });
  const rows = await collectionRepo().getMany(parsed.data);
  const indexOf = showcaseIndexes();
  const out = await Promise.all(rows.map((r) => collectionOut(r, indexOf)));
  return NextResponse.json({ ok: true, collections: out }, { headers: { "Cache-Control": "no-store" } });
}

// Сохранить коллекцию (план b2b-05): снимок своей расстановки → короткая ссылка. Квартира — только из
// реестра и только с витриной; номер отправки менеджера — только существующий и не отозванный.
export async function POST(req: Request): Promise<Response> {
  const limited = await guard(req, "collectionSave");
  if (limited) return limited;
  if (foreignOrigin(req)) return new Response(null, { status: 403 }); // чужой сайт — не пишем (b2b-07)
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
  const demoRaw = await loadDemoRaw(hit.apartment.sources.demoData);
  const idx = priceIndex(demoRaw);
  if (!idx.size) return NextResponse.json({ ok: false, error: "showcase_unavailable" }, { status: 503 });
  const canon = (sk: { sid: string } | undefined) => {
    if (!sk) return { ok: true as const, sku: undefined };
    const e = idx.get(sk.sid);
    if (!e) return { ok: false as const, sku: undefined };
    const { priceAt: _p, ...rest } = e;
    return { ok: true as const, sku: rest };
  };
  // КОМНАТА И СТИЛЬ (v3, demo-16 шаг 2): корзина считает сертификат по комнатам — комната должна быть у квартиры, а стиль и
  // комната — совпадать с опубликованным вариантом, от которого расстановка (Codex 18.10 п.10). v1/v2 — прежние страницы, как было
  if (parsed.data.schemaVersion === 3) {
    const rooms = hit.apartment.rooms;
    if (rooms.length && !rooms.some((r) => r.id === parsed.data.roomId)) return NextResponse.json({ ok: false, error: "unknown_room" }, { status: 400 });
    const key = variantKey(demoRaw, parsed.data.baseVariant);
    if (!key || key.styleId !== parsed.data.styleId || key.roomId !== parsed.data.roomId) {
      return NextResponse.json({ ok: false, error: "variant_mismatch" }, { status: 400 });
    }
  }
  const items = parsed.data.items.map((i) => ({ i, c: canon(i.sku) }));
  const decor = parsed.data.decor.map((d) => ({ d, c: canon(d.sku) }));
  if ([...items, ...decor].some((x) => !x.c.ok)) return NextResponse.json({ ok: false, error: "unknown_product" }, { status: 400 });
  const clean = {
    ...parsed.data,
    // выбор опций застройщика — только существующие у квартиры включённые группы и их варианты (demo-06)
    developerOptions: canonDeveloperOptions(apartmentCard(hit).options, parsed.data.developerOptions),
    items: items.map(({ i, c }) => ({ ...i, ...(c.sku ? { sku: c.sku } : {}) })),
    decor: decor.map(({ d, c }) => ({ ...d, sku: c.sku! })),
  };
  // СЕКРЕТ РЕДАКТИРОВАНИЯ (demo-15): только тому, кто сохранил, — им переименовывают; в базе — хеш
  const editToken = randomToken();
  const row = await collectionRepo().create(hit.partner.id, clean, new Date(), editHashOf(editToken));
  return NextResponse.json({ ok: true, id: row.id, editToken });
}
