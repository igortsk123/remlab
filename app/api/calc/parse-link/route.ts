import { NextResponse } from "next/server";
import { z } from "zod";
import { calcKind, type MaterialSpec } from "@/contracts/calc";
import { parseProductHtml } from "@/lib/calc/link-parse";
import { aiExtractSpec, KEY_FIELDS } from "@/lib/calc/link-parse-ai";

export const runtime = "nodejs";

const bodySchema = z.object({ url: z.string().url(), kind: calcKind });

// Серверный парс ссылки (без CORS, с таймаутом). При неудаче — ok:false + 200: клиент переходит к ручному вводу.
export async function POST(req: Request): Promise<Response> {
  const parsed = bodySchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ ok: false, error: "bad_request" }, { status: 400 });
  const { url, kind } = parsed.data;
  try {
    const res = await fetch(url, {
      headers: { "user-agent": "Mozilla/5.0 (compatible; remlab/1.0; +https://remont-lab.online)", "accept-language": "ru" },
      signal: AbortSignal.timeout(8000),
      redirect: "follow",
    });
    if (!res.ok) return NextResponse.json({ ok: false, error: `http_${res.status}` });
    const html = (await res.text()).slice(0, 2_000_000); // крупные карточки магазинов: цена/характеристики бывают за 500 КБ
    const result = parseProductHtml(html, kind);

    // ИИ-фолбэк: детерминированный парсер пропустил ключевые поля → дочитать через OpenAI (только пустое).
    const missing = KEY_FIELDS[kind].filter((k) => result.spec[k] == null);
    if (missing.length > 0 && process.env.OPENAI_API_KEY) {
      const bodyText = html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
      const aiSpec = await aiExtractSpec(bodyText, kind, missing);
      const target = result.spec as Record<string, number>;
      for (const [k, v] of Object.entries(aiSpec)) {
        if (result.spec[k as keyof MaterialSpec] == null && typeof v === "number") target[k] = v;
      }
    }

    return NextResponse.json({ ok: true, ...result });
  } catch {
    return NextResponse.json({ ok: false, error: "unreachable" });
  }
}
