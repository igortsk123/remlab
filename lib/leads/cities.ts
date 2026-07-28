// Справочник городов РФ (П7): hflabs/city (CC BY-SA 4.0), сгенерирован tools/update-cities.mjs.
// Серверный поиск для автокомплита модалки (клиенту весь JSON не шлём — 100+ КБ).

import data from "@/data/ru-cities.json";

export type City = { n: string; r: string; lat: number; lon: number };

const CITIES: City[] = (data as { cities: City[] }).cities;

// Поиск по префиксу (регистронезависимо, «ё»≈«е»); сначала точные префиксы, потом вхождения.
export function searchCities(q: string, limit = 8): City[] {
  const norm = (s: string) => s.toLowerCase().replace(/ё/g, "е").trim();
  const nq = norm(q);
  if (nq.length < 2) return [];
  const starts: City[] = [];
  const includes: City[] = [];
  for (const c of CITIES) {
    const n = norm(c.n);
    if (n.startsWith(nq)) starts.push(c);
    else if (n.includes(nq)) includes.push(c);
    if (starts.length >= limit) break;
  }
  return [...starts, ...includes].slice(0, limit);
}

export function cityExists(name: string): boolean {
  const norm = (s: string) => s.toLowerCase().replace(/ё/g, "е").trim();
  const n = norm(name);
  return CITIES.some((c) => norm(c.n) === n);
}
