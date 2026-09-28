import { NextResponse } from "next/server";
import { z } from "zod";

import { configuration } from "@/contracts/configurator";
import { loadFlat3d } from "@/lib/configurator/data";
import { buildQuote, revisions } from "@/lib/configurator/quote";
import { saveConfig } from "@/lib/configurator/repo";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Сохранение подбора покупателя. Цену пересчитываем на сервере — клиентской верить нельзя.
// Контакт НЕ принимаем: заявки идут существующим лид-потоком, здесь персональных данных нет
// (разбор Codex 28.09 — публичная ссылка не должна их носить).
const Body = z.object({ configuration });

export async function POST(req: Request): Promise<Response> {
  const parsed = Body.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });

  const { apartment, catalogue } = loadFlat3d();
  const cfg = parsed.data.configuration;
  if (cfg.apartmentId !== apartment.id) {
    return NextResponse.json({ error: "неизвестная квартира" }, { status: 400 });
  }
  if (Object.keys(cfg.selections).length > 200) {
    return NextResponse.json({ error: "слишком большой подбор" }, { status: 400 });
  }

  try {
    const quote = buildQuote(apartment, catalogue, cfg);
    const rev = revisions(apartment, catalogue);
    const id = await saveConfig({ configuration: cfg, quote, ...rev });
    return NextResponse.json({ id, quote });
  } catch {
    return NextResponse.json({ error: "не удалось сохранить" }, { status: 500 });
  }
}
