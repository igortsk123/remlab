// Оплата через YooKassa (К5). Без ключей (YOOKASSA_SHOP_ID/SECRET_KEY) — не сконфигурировано,
// платные функции деградируют (createPayment → null). Ключи — только в .env на сервере, не в git.

import { randomUUID } from "node:crypto";

const SHOP_ID = process.env.YOOKASSA_SHOP_ID;
const SECRET = process.env.YOOKASSA_SECRET_KEY;

export function paymentConfigured(): boolean {
  return Boolean(SHOP_ID && SECRET);
}

// Создать платёж → URL подтверждения (redirect) или null (не сконфигурировано / ошибка).
export async function createPayment(p: { amountRub: number; description: string; returnUrl: string }): Promise<string | null> {
  if (!SHOP_ID || !SECRET) return null;
  try {
    const res = await fetch("https://api.yookassa.ru/v3/payments", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "Idempotence-Key": randomUUID(),
        Authorization: `Basic ${Buffer.from(`${SHOP_ID}:${SECRET}`).toString("base64")}`,
      },
      body: JSON.stringify({
        amount: { value: p.amountRub.toFixed(2), currency: "RUB" },
        capture: true,
        confirmation: { type: "redirect", return_url: p.returnUrl },
        description: p.description,
      }),
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return typeof data?.confirmation?.confirmation_url === "string" ? data.confirmation.confirmation_url : null;
  } catch {
    return null;
  }
}
