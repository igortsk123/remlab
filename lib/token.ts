// Случайный публичный токен: 16 байт (128 бит) → 22 символа base64url. Для ссылок, которые
// работают как ключ (отправка, страница менеджера): перебрать такой нельзя ни при каких лимитах.

import { randomBytes } from "node:crypto";

export function randomToken(bytes = 16): string {
  return randomBytes(bytes).toString("base64url");
}

export const TOKEN_RE = /^[A-Za-z0-9_-]{22}$/;

/** Номер задания пробы (`trial_jobs.id`, T-20261119-02): тот же токен, но первый знак — буква или цифра. Номер уходит стадиям Python
 *  позиционным аргументом и именем папки: `-…` argparse примет за флаг, `_…` отвергают `trial_bundle._check_input` и
 *  `trial_demo` (`[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`) — загрузка с таким номером (2 из 64) теряла тур без следа. Выбор — повтором: остальные
 *  знаки и длина прежние, ключи старых заданий (в том числе на `_`/`-`) по-прежнему принимает `TOKEN_RE`. Прочие токены — `randomToken`. */
export const JOB_ID_START_RE = /^[A-Za-z0-9]/;

export function randomJobId(gen: () => string = randomToken): string {
  for (let i = 0; i < 64; i++) {
    const id = gen();
    if (TOKEN_RE.test(id) && JOB_ID_START_RE.test(id)) return id;
  }
  throw new Error("job_id_unavailable");
}
