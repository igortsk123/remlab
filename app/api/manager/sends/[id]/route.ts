import { NextResponse } from "next/server";
import { z } from "zod";

import { managerStatus } from "@/contracts/send";
import { managerFromRequest } from "@/lib/manager-auth";
import { guard } from "@/lib/ratelimit/http";
import { revokeSend, setStatusByManager } from "@/modules/sends/service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const Body = z.union([z.object({ status: managerStatus }), z.object({ revoke: z.literal(true) })]);

// Статус или отзыв ссылки со страницы менеджера — только своей ссылки.
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const limited = await guard(req, "manager");
  if (limited) return limited;
  const m = await managerFromRequest(req);
  if (!m) return NextResponse.json({ ok: false }, { status: 403 });
  const { id } = await ctx.params;
  const parsed = Body.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ ok: false }, { status: 400 });
  const ok = "status" in parsed.data ? await setStatusByManager(m, id, parsed.data.status) : await revokeSend(m, id);
  return NextResponse.json({ ok }, { status: ok ? 200 : 404 });
}
