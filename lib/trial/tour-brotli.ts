// Brotli для страницы тура (T-20261110-43): Caddy 2.8 brotli не умеет (`encode zstd gzip`), Next его тоже не отдаёт, а страница —
// 1,2 МБ разметки: zstd/gzip ≈ 400 КБ, brotli 11 ≈ 296 КБ (−26 %, на 2 Мбит/с ≈ −0,4 с). Сжатие 11 стоит ~2 с процессора — на запрос
// так нельзя: первый ответ — уровень 5 (≈ 40 мс, ≈ 340 КБ), уровень 11 считается фоном (по одному за раз) и заменяет запись.
// Ключ — метка страницы (ETag: тело одно — метка одна), записи — в памяти процесса, LRU не больше 32 МБ.
// Caddy уже сжатый ответ не пережимает (`Content-Encoding` стоит) — проверено пробой (`.t43`, отчёт T-43).

import { promisify } from "node:util";
import zlib from "node:zlib";

export const BROTLI_CACHE_MAX_BYTES = 32 * 1024 * 1024;
const FAST = 5;
const BEST = 11;

const compress = promisify(zlib.brotliCompress);
const brotli = (raw: Buffer, quality: number): Promise<Buffer> =>
  compress(raw, { params: { [zlib.constants.BROTLI_PARAM_QUALITY]: quality, [zlib.constants.BROTLI_PARAM_SIZE_HINT]: raw.length } });

const cache = new Map<string, Buffer>();
let total = 0;
let bestBusy = false;

function put(key: string, body: Buffer): void {
  const old = cache.get(key);
  if (old) {
    total -= old.length;
    cache.delete(key);
  }
  cache.set(key, body);
  total += body.length;
  for (const [k, b] of cache) {
    if (total <= BROTLI_CACHE_MAX_BYTES) break;
    cache.delete(k);
    total -= b.length;
  }
}

/** Просит ли клиент brotli: `br` в Accept-Encoding с q > 0 (`br;q=0` — отказ). */
export function acceptsBrotli(acceptEncoding: string | null | undefined): boolean {
  return (acceptEncoding ?? "").split(",").some((part) => {
    const [name, ...params] = part.trim().toLowerCase().split(";");
    if (name?.trim() !== "br") return false;
    const q = params.map((p) => p.trim()).find((p) => p.startsWith("q="));
    return q === undefined || Number(q.slice(2)) > 0;
  });
}

/** Сжатая страница по метке: есть в памяти — она (запись освежается в LRU); нет — уровень 5 сейчас, уровень 11 фоном. */
export async function brotliPage(tag: string, html: string): Promise<Buffer> {
  const hit = cache.get(tag);
  if (hit) {
    put(tag, hit);
    return hit;
  }
  const raw = Buffer.from(html, "utf8");
  const fast = await brotli(raw, FAST);
  put(tag, fast);
  if (!bestBusy) {
    bestBusy = true;
    // фоновое сжатие — в пуле потоков libuv, не в потоке запросов; одно за раз, чтобы пул не забивался (чтение файлов идёт через него же)
    brotli(raw, BEST)
      .then((best) => {
        if (cache.has(tag) && best.length < (cache.get(tag)?.length ?? 0)) put(tag, best);
      })
      .catch((e: unknown) => console.error(`tour brotli: ${e instanceof Error ? e.message : String(e)}`.slice(0, 300)))
      .finally(() => {
        bestBusy = false;
      });
  }
  return fast;
}

/** Для тестов: сколько записей и байт в памяти; сброс. */
export const brotliCacheStats = (): { entries: number; bytes: number } => ({ entries: cache.size, bytes: total });
export function brotliCacheReset(): void {
  cache.clear();
  total = 0;
}
