import { NextResponse } from "next/server";
import { track } from "@/lib/analytics";
import { fetchPaymentStatus, paymentConfigured } from "@/lib/payments/yookassa";
import { isYookassaIp } from "@/lib/payments/yookassa-ip";
import { clientIp } from "@/lib/ratelimit/http";

export const runtime = "nodejs";

// Вебхук YooKassa: подтверждение оплаты. Подписи у ЮKassa нет, поэтому (план b2b-01):
// 1) отправитель — только из её адресов, иначе 403; 2) телу не верим — статус платежа
// перезапрашиваем у API по id; 3) ключей магазина нет — платежей быть не может, 403.
export async function POST(req: Request): Promise<Response> {
  if (!paymentConfigured() || !isYookassaIp(clientIp(req.headers))) {
    return NextResponse.json({ ok: false }, { status: 403 });
  }
  const body = await req.json().catch(() => null);
  if (body?.event !== "payment.succeeded") return NextResponse.json({ ok: true }); // прочие события нам не нужны
  const paymentId = typeof body?.object?.id === "string" ? body.object.id : "";
  if (!paymentId) return NextResponse.json({ ok: false }, { status: 400 });
  const status = await fetchPaymentStatus(paymentId);
  // API не ответил — 503: ЮKassa повторит уведомление, иначе оплата потерялась бы молча.
  if (status === null) return NextResponse.json({ ok: false }, { status: 503 });
  if (status === "succeeded") {
    await track("pack_unlocked", "system", { provider: "yookassa", paymentId });
  }
  return NextResponse.json({ ok: true });
}
