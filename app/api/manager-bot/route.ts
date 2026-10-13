import { NextResponse } from "next/server";

import { safeEqual } from "@/lib/safe-equal";
import { handleBotUpdate, type BotUpdate } from "@/modules/sends/bot";
import { MANAGER_TG_TOKEN } from "@/modules/sends/dispatch";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Вебхук бота менеджеров (план b2b-02). Без токена бота или секрета вебхука — закрыто.
// Тело апдейта не логируем: в нём заметка менеджера («Вася, после показа»).
export async function POST(req: Request): Promise<Response> {
  const token = MANAGER_TG_TOKEN();
  const secret = process.env.MANAGER_TG_WEBHOOK_SECRET || "";
  if (!token || !secret || !safeEqual(req.headers.get("x-telegram-bot-api-secret-token") ?? "", secret)) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }
  const update = (await req.json().catch(() => null)) as BotUpdate | null;
  if (typeof update?.update_id !== "number") return NextResponse.json({ ok: true });
  try {
    await handleBotUpdate(update, token);
  } catch {
    // 500 → Telegram повторит; повтор отсечёт tg_updates только если запись успела — иначе обработаем заново
    return NextResponse.json({ ok: false }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}
