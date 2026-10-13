import { NextResponse } from "next/server";

import { safeEqual } from "@/lib/safe-equal";
import { runRetention } from "@/modules/retention/run";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Удаление по срокам хранения (план b2b-04): раз в сутки зовёт systemd-таймер `remlab-retention` по сети
// remlab-net; снаружи Caddy отвечает 404, без INTERNAL_API_TOKEN — 403.
export async function POST(req: Request): Promise<Response> {
  const token = process.env.INTERNAL_API_TOKEN;
  if (!token || !safeEqual(req.headers.get("x-internal-token") ?? "", token)) {
    return NextResponse.json({ ok: false }, { status: 403 });
  }
  return NextResponse.json({ ok: true, results: await runRetention() });
}
