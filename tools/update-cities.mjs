#!/usr/bin/env node
// Обновление справочника городов РФ (П7): hflabs/city (CC BY-SA 4.0, атрибуция в data/ru-cities.json)
// → компактный JSON [{n:город, r:регион, lat, lon}]. Запуск: node tools/update-cities.mjs
import { writeFileSync } from "node:fs";
const SRC = "https://raw.githubusercontent.com/hflabs/city/master/city.csv";
const csv = await (await fetch(SRC)).text();
const lines = csv.trim().split("\n");
const header = lines[0].split(",");
const idx = (k) => header.indexOf(k);
const [iRegT, iReg, iCity, iLat, iLon] = ["region_type", "region", "city", "geo_lat", "geo_lon"].map(idx);
// Простенький CSV-парс с кавычками (поля датасета без переводов строк внутри).
const parse = (line) => {
  const out = []; let cur = "", q = false;
  for (const ch of line) {
    if (ch === '"') q = !q;
    else if (ch === "," && !q) { out.push(cur); cur = ""; }
    else cur += ch;
  }
  out.push(cur); return out;
};
// Города фед. значения (Москва/СПб/Севастополь) в датасете записаны РЕГИОНОМ (city пусто,
// region_type «г») — берём имя из region, иначе теряем крупнейшие города.
const cities = lines.slice(1).map(parse)
  .filter((c) => c[iCity] || c[iRegT] === "г")
  .map((c) => ({
    n: c[iCity] || c[iReg],
    r: c[iCity] ? `${c[iReg]} ${c[iRegT]}`.trim() : "город фед. значения",
    lat: Number(c[iLat]), lon: Number(c[iLon]),
  }));
cities.sort((a, b) => a.n.localeCompare(b.n, "ru"));
const out = { _license: "hflabs/city, CC BY-SA 4.0 (https://github.com/hflabs/city)", cities };
writeFileSync("data/ru-cities.json", JSON.stringify(out));
console.log(`ru-cities.json: ${cities.length} городов`);
