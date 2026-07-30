// Слой добычи HTML страницы товара (link-fetch-max): прямой fetch с браузерными заголовками →
// фолбэк через резидентский прокси из env PARSE_PROXY_URLS (список через запятую, перебор) для
// магазинов, режущих ДЦ-IP. Прокси-пул общий с другим проектом и с квотой по трафику → страница
// режется по байтам. Причины фейлов логируем — иначе прод неотлаживаем.

import { fetch as undiciFetch, ProxyAgent } from "undici";

export type FetchPageResult =
  | { ok: true; html: string; via: "direct" | "proxy" }
  | { ok: false; error: "unreachable" | `http_${number}` | "bad_url" };

const MAX_BYTES = 2_000_000; // цена/характеристики бывают за 500 КБ, но квоту прокси бережём
const DIRECT_TIMEOUT_MS = 8000;
const PROXY_TIMEOUT_MS = 20_000; // резидентский пул медленный (~4 Мбит/с)

// Заголовки как у реального Chrome: часть магазинов режет «честных ботов» по UA.
const BROWSER_HEADERS = {
  "user-agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
  accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "accept-language": "ru-RU,ru;q=0.9",
} as const;

// SSRF-guard: серверный fetch по юзерскому URL не должен ходить во внутреннюю сеть.
export function isPrivateHost(hostname: string): boolean {
  const h = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (h === "localhost" || h.endsWith(".local") || h.endsWith(".internal")) return true;
  if (h === "::1" || h.startsWith("fc") || h.startsWith("fd") || h.startsWith("fe80")) return true;
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(h);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return a === 0 || a === 10 || a === 127 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
}

// Ответ «мусорный»? Страница-челлендж/заглушка вместо карточки: подозрительно короткий HTML
// без og:-меты и цены. Порог осторожный — челлендж Ozon ≈ 4 КБ, реальные карточки ≥ 50 КБ.
export function looksLikeStub(html: string): boolean {
  return html.length < 6000 && !/property=["']og:title["']/i.test(html) && !/₽|руб/i.test(html);
}

// Читаем тело потоком с обрезкой по байтам (не качаем мегабайты через квотируемый прокси).
async function readCapped(body: ReadableStream<Uint8Array> | null, cap: number): Promise<string> {
  if (!body) return "";
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (total < cap) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    total += value.byteLength;
  }
  await reader.cancel().catch(() => {});
  const merged = new Uint8Array(Math.min(total, cap));
  let off = 0;
  for (const c of chunks) {
    const part = c.subarray(0, Math.min(c.byteLength, merged.byteLength - off));
    merged.set(part, off);
    off += part.byteLength;
    if (off >= merged.byteLength) break;
  }
  return new TextDecoder().decode(merged);
}

type Attempt = { status?: number; html?: string; err?: string };

async function attemptDirect(url: string): Promise<Attempt> {
  try {
    const res = await fetch(url, {
      headers: BROWSER_HEADERS,
      signal: AbortSignal.timeout(DIRECT_TIMEOUT_MS),
      redirect: "follow",
    });
    if (!res.ok) return { status: res.status };
    return { status: res.status, html: await readCapped(res.body, MAX_BYTES) };
  } catch (e) {
    return { err: e instanceof Error ? e.message : String(e) };
  }
}

async function attemptProxy(url: string, proxyUrl: string): Promise<Attempt> {
  const agent = new ProxyAgent(proxyUrl);
  try {
    const res = await undiciFetch(url, {
      dispatcher: agent,
      headers: BROWSER_HEADERS,
      signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
      redirect: "follow",
    });
    if (!res.ok) return { status: res.status };
    const html = await readCapped(res.body as ReadableStream<Uint8Array> | null, MAX_BYTES);
    return { status: res.status, html };
  } catch (e) {
    return { err: e instanceof Error ? e.message : String(e) };
  } finally {
    await agent.close().catch(() => {});
  }
}

// Список прокси из env: "http://user:pass@host:port,http://user:pass@host:port2". Часть портов
// пула штатно отдаёт 407/503 → перебираем по порядку (максимум 3).
export function proxyUrlsFromEnv(raw: string | undefined): string[] {
  return (raw ?? "").split(",").map((s) => s.trim()).filter((s) => /^https?:\/\//.test(s)).slice(0, 3);
}

export async function fetchProductPage(url: string): Promise<FetchPageResult> {
  let host: string;
  try {
    host = new URL(url).hostname;
  } catch {
    return { ok: false, error: "bad_url" };
  }
  if (isPrivateHost(host)) return { ok: false, error: "bad_url" };

  const direct = await attemptDirect(url);
  if (direct.html && !looksLikeStub(direct.html)) return { ok: true, html: direct.html, via: "direct" };
  console.error(`[fetch-page] direct fail ${host}: status=${direct.status ?? "-"} err=${direct.err ?? "-"} stub=${!!direct.html}`);

  // Прокси пробуем для ЛЮБОГО магазина (включая Ozon/WB — режут ДЦ-IP). ⚠️ Известное ограничение:
  // Ozon блокирует и IP этого прокси-пула (капча/«выключите VPN») — серверно непробиваем ни curl,
  // ни браузером, ни резид./моб. IP (проверено 2026-07-30). Для Ozon нужен прокси-анблокер
  // (Bright Data/Zyte) — тогда сработает без правок кода. Пока Ozon-ссылки → ошибка чтения.
  let lastStatus: number | undefined = direct.status;
  for (const proxyUrl of proxyUrlsFromEnv(process.env.PARSE_PROXY_URLS)) {
    const viaProxy = await attemptProxy(url, proxyUrl);
    if (viaProxy.html && !looksLikeStub(viaProxy.html)) {
      console.error(`[fetch-page] proxy ok ${host}: ${viaProxy.html.length}b`);
      return { ok: true, html: viaProxy.html, via: "proxy" };
    }
    console.error(`[fetch-page] proxy fail ${host}: status=${viaProxy.status ?? "-"} err=${viaProxy.err ?? "-"}`);
    lastStatus = viaProxy.status ?? lastStatus;
  }

  if (lastStatus && lastStatus >= 400) return { ok: false, error: `http_${lastStatus}` };
  return { ok: false, error: "unreachable" };
}
