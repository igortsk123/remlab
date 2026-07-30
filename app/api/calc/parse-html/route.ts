import { NextResponse } from "next/server";
import { z } from "zod";
import { calcKind } from "@/contracts/calc";
import { parseProductFull } from "@/lib/calc/parse-product";

export const runtime = "nodejs";

// Сохранённый браузером HTML (Ctrl+S → «только HTML») уже содержит исполненный JS-DOM —
// путь для магазинов с антиботом (Ozon/WB), которые серверным fetch непробиваемы.
const bodySchema = z.object({ html: z.string().min(200).max(4_000_000), kind: calcKind });

// Парс загруженной пользователем сохранённой страницы — тот же пайплайн, что parse-link.
export async function POST(req: Request): Promise<Response> {
  const parsed = bodySchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ ok: false, error: "bad_request" }, { status: 400 });
  const { html, kind } = parsed.data;

  const result = await parseProductFull(html, kind);
  return NextResponse.json({ ok: true, via: "file", ...result });
}
