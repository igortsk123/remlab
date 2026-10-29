import { NextResponse } from "next/server";
import { z } from "zod";

import { guard } from "@/lib/ratelimit/http";
import { reviewRepo } from "@/modules/owner-reviews/repository";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Отметки владельца на проверочных страницах /test/* (ADR-0275). Страницы внутренние и без кодов (решение владельца
// 05.09), поэтому защита — лимит частоты, белый список видов и вердиктов, короткие поля. Читает и DEV (курсор after).
// style_note — комментарий к товару на странице отметок стиля: сохраняется сам по ходу ввода, каждая версия — строка (29.10).
const KINDS = {
  style: ["yes", "no", "clear"],
  style_note: ["note"],
  quarantine: ["accept", "reject", "cut"],
  orient: ["cur", "new", "y0", "y90", "y180", "y270"],
} as const;
const Body = z.object({
  kind: z.enum(["style", "style_note", "quarantine", "orient"]),
  key: z.string().min(1).max(160).regex(/^[\p{L}\p{N}_:|.\- ]+$/u),
  verdict: z.string().max(10),
  comment: z.string().trim().max(1000).optional(),
});

export async function POST(req: Request): Promise<Response> {
  const limited = await guard(req, "ownerReview");
  if (limited) return limited;
  const p = Body.safeParse(await req.json().catch(() => null));
  if (!p.success || !(KINDS[p.data.kind] as readonly string[]).includes(p.data.verdict)) {
    return NextResponse.json({ ok: false, error: "bad_request" }, { status: 400 });
  }
  const row = await reviewRepo().add({ kind: p.data.kind, itemKey: p.data.key, verdict: p.data.verdict, comment: p.data.comment || null });
  return NextResponse.json({ ok: true, id: row.id });
}

export async function GET(req: Request): Promise<Response> {
  const limited = await guard(req, "ownerReview");
  if (limited) return limited;
  const u = new URL(req.url);
  const kind = u.searchParams.get("kind") ?? "";
  if (!(kind in KINDS)) return NextResponse.json({ ok: false }, { status: 400 });
  const after = Math.max(0, Number(u.searchParams.get("after") ?? 0) || 0);
  const rows = await reviewRepo().list(kind, after, 2000);
  return NextResponse.json({ ok: true, rows }, { headers: { "Cache-Control": "no-store" } });
}
