import { NextResponse } from "next/server";

export const runtime = "nodejs";

// Вебхук MAX-бота (П7) — СКЕЛЕТ. Возможности MAX Bot API (отправка ботом, deep-link start,
// вебхуки) проверим при получении токена от владельца; до этого канал MAX деградирует:
// заявка собирает город (+контакт), ответ — вручную. TODO(owner): токен → реализация по аналогии с tg-client.
export async function POST(): Promise<Response> {
  return NextResponse.json({ ok: true });
}
