// Адреса, с которых ЮKassa шлёт уведомления (план b2b-01). Подписи у её вебхуков нет; документация
// («Входящие уведомления» → «Проверка подлинности», yookassa.ru/developers/using-api/webhooks)
// предлагает проверять IP отправителя и/или перезапрашивать объект через API. Делаем оба.

const V4: [string, number][] = [
  ["185.71.76.0", 27],
  ["185.71.77.0", 27],
  ["77.75.153.0", 25],
  ["77.75.156.11", 32],
  ["77.75.156.35", 32],
  ["77.75.154.128", 25],
];
const V6: [string, number][] = [["2a02:5180::", 32]];

function v4ToInt(ip: string): number | null {
  const p = ip.split(".");
  if (p.length !== 4) return null;
  let n = 0;
  for (const s of p) {
    if (!/^\d{1,3}$/.test(s) || Number(s) > 255) return null;
    n = n * 256 + Number(s);
  }
  return n;
}

function v6ToBits(ip: string): string | null {
  const [head, tail, extra] = ip.toLowerCase().split("::");
  if (extra !== undefined) return null;
  const h = head ? head.split(":") : [];
  const t = tail !== undefined && tail ? tail.split(":") : [];
  const fill = tail === undefined ? 0 : 8 - h.length - t.length;
  if (fill < 0 || (tail === undefined && h.length !== 8)) return null;
  const parts = [...h, ...Array<string>(fill).fill("0"), ...t];
  if (parts.some((x) => !/^[0-9a-f]{1,4}$/.test(x))) return null;
  return parts.map((x) => parseInt(x, 16).toString(2).padStart(16, "0")).join("");
}

export function isYookassaIp(raw: string): boolean {
  const ip = raw.trim().replace(/^::ffff:/i, "");
  const n4 = v4ToInt(ip);
  if (n4 !== null) {
    return V4.some(([net, bits]) => {
      const base = v4ToInt(net)!;
      const size = 2 ** (32 - bits);
      return Math.floor(n4 / size) === Math.floor(base / size);
    });
  }
  const b6 = v6ToBits(ip);
  if (!b6) return false;
  return V6.some(([net, bits]) => v6ToBits(net)!.slice(0, bits) === b6.slice(0, bits));
}
