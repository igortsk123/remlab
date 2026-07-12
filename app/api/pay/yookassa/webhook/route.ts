import { NextResponse } from "next/server";
import { track } from "@/lib/analytics";

export const runtime = "nodejs";

// Вебхук YooKassa: подтверждение оплаты. MVP — фиксируем успех событием (полный анлок фичи — позже).
export async function POST(req: Request): Promise<Response> {
  const body = await req.json().catch(() => null);
  const succeeded = body?.event === "payment.succeeded" || body?.object?.status === "succeeded";
  if (succeeded) {
    await track("pack_unlocked", "system", { provider: "yookassa", paymentId: String(body?.object?.id ?? "") });
  }
  return NextResponse.json({ ok: true });
}
