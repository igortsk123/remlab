import { NextResponse } from "next/server";
import { z } from "zod";
import { calcKind } from "@/contracts/calc";
import { fetchProductPage } from "@/lib/calc/fetch-page";
import { parseProductFull } from "@/lib/calc/parse-product";

export const runtime = "nodejs";

const bodySchema = z.object({ url: z.string().url(), kind: calcKind });

// Серверный парс ссылки (без CORS): добыча HTML (прямой fetch → резидентский прокси для магазинов,
// режущих ДЦ-IP) → полный парс (regex + JSON-LD + ИИ-дочитка). При неудаче — ok:false + 200 с
// кодом причины (клиент показывает ошибку + ручной ввод).
export async function POST(req: Request): Promise<Response> {
  const parsed = bodySchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ ok: false, error: "bad_request" }, { status: 400 });
  const { url, kind } = parsed.data;

  const page = await fetchProductPage(url);
  if (!page.ok) return NextResponse.json({ ok: false, error: page.error });

  const result = await parseProductFull(page.html, kind);
  return NextResponse.json({ ok: true, via: page.via, ...result });
}
