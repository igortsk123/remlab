"use server";

import { redirect } from "next/navigation";
import { getSessionId } from "@/lib/session";
import { track } from "@/lib/analytics";
import { createPayment, paymentConfigured } from "@/lib/payments/yookassa";

const APP_URL = process.env.APP_URL ?? "https://remont-lab.online";

// Из результата калькулятора → визуализация по фото (существующий /start-флоу).
// Оплата настроена (ключи YooKassa) → сперва платёж 60 ₽ (redirect на подтверждение); иначе сразу к виз.
export async function startCalcViz(): Promise<void> {
  const sessionId = await getSessionId();
  await track("viz_started", sessionId, { source: "calc", paid: paymentConfigured() });
  if (paymentConfigured()) {
    const url = await createPayment({
      amountRub: 60,
      description: "Визуализация комнаты по фото",
      returnUrl: `${APP_URL}/start`,
    });
    if (url) redirect(url);
  }
  redirect("/start");
}
