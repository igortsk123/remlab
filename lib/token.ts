// Случайный публичный токен: 16 байт (128 бит) → 22 символа base64url. Для ссылок, которые
// работают как ключ (отправка, страница менеджера): перебрать такой нельзя ни при каких лимитах.

import { randomBytes } from "node:crypto";

export function randomToken(bytes = 16): string {
  return randomBytes(bytes).toString("base64url");
}

export const TOKEN_RE = /^[A-Za-z0-9_-]{22}$/;
