import { NextResponse } from "next/server";

import { readConfig } from "@/lib/configurator/repo";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Чтение подбора по публичной ссылке: конфигурация и цена, БЕЗ контакта — его в ответе нет
// никогда, даже если он сохранён (менеджер видит контакт в своей системе, не по ссылке).
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await ctx.params;
  if (!/^[a-f0-9]{8,32}$/i.test(id)) return NextResponse.json({ error: "неверная ссылка" }, { status: 400 });
  const found = await readConfig(id);
  if (!found) return NextResponse.json({ error: "подбор не найден" }, { status: 404 });
  return NextResponse.json({
    id: found.id,
    configuration: found.configuration,
    quote: found.quote,
    createdAt: found.createdAt,
  });
}
