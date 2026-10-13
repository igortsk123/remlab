import { NextResponse } from "next/server";
import { z } from "zod";

import { checkLimits, PRESETS } from "@/lib/ratelimit";
import { limitResponse } from "@/lib/ratelimit/http";
import { safeEqual } from "@/lib/safe-equal";
import { shareRequestRepo } from "@/modules/share-requests/repository";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// ВНУТРЕННИЙ приём заявки «отправить подборку себе» (план b2b-01, ADR-0248). Зовёт только сервис
// кадров (`tools/scout/draft_service.py`) по сети remlab-net; снаружи Caddy отвечает 404, а без
// общего секрета INTERNAL_API_TOKEN роут закрыт (не задан → 403, «пускать всех» нельзя).
const Body = z.object({
  shareId: z.string().regex(/^[0-9a-f]{6,40}$/),
  shareUrl: z.string().url().max(300),
  channel: z.enum(["telegram", "max", "sms", ""]),
  contact: z.string().trim().min(1).max(120),
  shotCount: z.number().int().min(0).max(100),
  ip: z.string().max(64).optional(),
});

export async function POST(req: Request): Promise<Response> {
  const token = process.env.INTERNAL_API_TOKEN;
  if (!token || !safeEqual(req.headers.get("x-internal-token") ?? "", token)) {
    return NextResponse.json({ ok: false }, { status: 403 });
  }
  const parsed = Body.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ ok: false, error: "bad_request" }, { status: 400 });

  const limit = await checkLimits(PRESETS.share(parsed.data.ip || "unknown"));
  if (!limit.ok) return limitResponse(limit);

  const repo = shareRequestRepo();
  try {
    await repo.purgeExpired(); // срок хранения контакта — 90 дней, чистим при каждой новой заявке
    const row = await repo.create({ ...parsed.data, channel: parsed.data.channel || "unknown" });
    return NextResponse.json({ ok: true, id: row.id });
  } catch {
    return NextResponse.json({ ok: false, error: "store_failed" }, { status: 500 });
  }
}
