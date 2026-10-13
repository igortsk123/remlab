// Вызов Telegram Bot API с различимым результатом (план b2b-02). У `lib/leads/tg.ts` любой сбой —
// одинаковый `null`; очереди сигналов нужно отличать «нет токена» (не повторять), «Telegram отказал»
// (403 — менеджер заблокировал бота, не повторять) и «сеть/таймаут/5xx» (повторить позже).

const API = "https://api.telegram.org";

export type TgResult<T = unknown> =
  | { ok: true; result: T }
  | { ok: false; retry: boolean; error: string };

export type TgFetch = (url: string, init: RequestInit) => Promise<Response>;

export async function tgCall<T = unknown>(
  token: string, method: string, body: Record<string, unknown>, fetchImpl: TgFetch = fetch,
): Promise<TgResult<T>> {
  if (!token) return { ok: false, retry: false, error: "no_token" };
  try {
    const res = await fetchImpl(`${API}/bot${token}/${method}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10_000),
    });
    const data = (await res.json().catch(() => null)) as { ok?: boolean; result?: T; description?: string } | null;
    if (data?.ok) return { ok: true, result: data.result as T };
    const retry = res.status === 429 || res.status >= 500;
    return { ok: false, retry, error: `${res.status} ${data?.description ?? ""}`.trim().slice(0, 200) };
  } catch (e) {
    return { ok: false, retry: true, error: String((e as Error)?.name ?? e).slice(0, 200) };
  }
}

/** Кнопки статуса под сигналом: менеджер ставит статус одним нажатием. */
export function statusKeyboard(sendId: string) {
  const b = (text: string, st: string) => ({ text, callback_data: `st:${sendId}:${st}` });
  return { inline_keyboard: [[b("Связались", "contacted"), b("Встреча", "meeting")], [b("Сделка", "deal"), b("Отказ", "lost")]] };
}
