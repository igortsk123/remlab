import { NextResponse } from "next/server";
import { z } from "zod";
import { calcKind } from "@/contracts/calc";
import { parseProductHtml } from "@/lib/calc/link-parse";

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
    const html = (await res.text()).slice(0, 500_000);
    return NextResponse.json({ ok: true, ...parseProductHtml(html, kind) });
  } catch {
    return NextResponse.json({ ok: false, error: "unreachable" });
  }
}
