import { NextResponse } from "next/server";
import { buildHealth, dbCheck, showcaseCheck } from "@/lib/health";

export const dynamic = "force-dynamic";

export async function GET() {
  const [db, showcase] = await Promise.all([dbCheck(), showcaseCheck()]);
  const h = buildHealth(new Date(), { db, showcase });
  return NextResponse.json(h, { status: h.ok ? 200 : 503, headers: { "Cache-Control": "no-store" } });
}
