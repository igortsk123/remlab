import { NextResponse } from "next/server";

import { safeEqual } from "@/lib/safe-equal";
import { flushSignals } from "@/modules/sends/dispatch";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Таймер сигналов (план b2b-02): раз в минуту сводки выбора и повторы доставки. Зовёт systemd-таймер
// `remlab-signals` по сети remlab-net; снаружи Caddy отвечает 404, без INTERNAL_API_TOKEN — 403.
export async function POST(req: Request): Promise<Response> {
  const token = process.env.INTERNAL_API_TOKEN;
  if (!token || !safeEqual(req.headers.get("x-internal-token") ?? "", token)) {
    return NextResponse.json({ ok: false }, { status: 403 });
  }
  return NextResponse.json({ ok: true, ...(await flushSignals()) });
}
