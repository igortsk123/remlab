import { after, NextResponse } from "next/server";

import { buyerEvent } from "@/contracts/send";
import { TOKEN_RE } from "@/lib/token";
import { guard } from "@/lib/ratelimit/http";
import { flushSignals } from "@/modules/sends/dispatch";
import { recordBuyerEvent } from "@/modules/sends/service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Действие покупателя по ссылке менеджера (план b2b-02). Принимает ТОЛЬКО события покупателя:
// статусы «встреча/сделка» отсюда не поставить. Срочные сигналы уходят сразу после ответа.
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const limited = await guard(req, "sendEvent");
  if (limited) return limited;
  const { id } = await ctx.params;
  const parsed = buyerEvent.safeParse(await req.json().catch(() => null));
  if (!TOKEN_RE.test(id) || !parsed.success) return NextResponse.json({ ok: false }, { status: 400 });
  const ok = await recordBuyerEvent(id, parsed.data);
  if (!ok) return NextResponse.json({ ok: false }, { status: 404 });
  after(() => flushSignals().then(() => undefined, () => undefined));
  return NextResponse.json({ ok: true });
}
