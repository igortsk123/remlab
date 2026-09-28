#!/usr/bin/env node
// Сборка каталога мебели для 3D-конфигуратора из лент демо (`/demo/`) — план apartment-3d-configurator.
//
// ПОЧЕМУ ИЗ ЛЕНТ ДЕМО: там товары уже прошли отбор конвейера (есть меш `msid` в индексе прода,
// живое фото, честные габариты из паспорта, стиль) — тот самый набор, который владелец смотрит
// на /demo/. Ничего не выдумываем: цена, габариты, картинка и модель берутся как есть.
//
// Запуск:  node tools/flat3d/build-catalogue.mjs [--demo <demo-data.json>] [--out data/flat3d/furniture.json]
// Идемпотентно: один и тот же вход даёт один и тот же выход (сортировка и отбор детерминированы).

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";

const RUB_PER_GBP = 112; // курс демо (план demo-en-gbp)
const MESH_BASE = "https://remont-lab.online/test/mesh-pilot10/";
const DEMO_IMG_BASE = "https://remont-lab.online/demo/";

const args = process.argv.slice(2);
const argOf = (name, def) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
};

const DEMO = argOf("--demo", "/home/pakar/scout-scenes/flat215-demo/demo-data.json");
const OUT = resolve(argOf("--out", "data/flat3d/furniture.json"));

/** Роль ленты → слот конфигуратора. Порядок вариантов внутри роли задаёт цена. */
const ROLE_PLAN = [
  { role: "диван", key: "sofa", category: "furniture", wRange: [170, 260], take: 4 },
  { role: "кресло", key: "armchair", category: "furniture", wRange: [60, 110], take: 4 },
  { role: "столик", key: "coffee-table", category: "furniture", wRange: [50, 130], take: 4 },
  { role: "тв-тумба", key: "tv-unit", category: "furniture", wRange: [90, 200], take: 4 },
  { role: "стол обеденный", key: "dining-table", category: "furniture", wRange: [90, 180], take: 4 },
  { role: "стул", key: "dining-chair", category: "furniture", wRange: [38, 60], take: 4 },
  { role: "торшер", key: "floor-lamp", category: "lighting", wRange: [20, 60], take: 4 },
  { role: "комод", key: "dresser", category: "storage", wRange: [70, 160], take: 4 },
  { role: "стеллаж", key: "shelf", category: "storage", wRange: [50, 160], take: 4 },
  { role: "пуф", key: "pouf", category: "furniture", wRange: [35, 90], take: 4 },
];

const TIER_BY_INDEX = ["base", "standard", "standard", "premium"];

async function fetchJson(url) {
  const res = await fetch(url, { signal: AbortSignal.timeout(30_000) });
  if (!res.ok) throw new Error(`${url} → HTTP ${res.status}`);
  return res.json();
}

/** Название по-английски делаем предсказуемым: роль + магазин + ключевое слово модели. */
const EN_ROLE = {
  диван: "Sofa",
  кресло: "Armchair",
  столик: "Coffee table",
  "тв-тумба": "TV unit",
  "стол обеденный": "Dining table",
  стул: "Dining chair",
  торшер: "Floor lamp",
  комод: "Chest of drawers",
  стеллаж: "Shelving unit",
  пуф: "Pouffe",
};

function gbp(priceRub) {
  return Math.max(0, Math.round(priceRub / RUB_PER_GBP));
}

/** Из ленты берём только то, у чего есть модель на проде и честные габариты. */
function candidates(feed, meshIndex, plan) {
  const seen = new Set();
  return feed
    .filter((p) => {
      const mid = p.msid || p.sid;
      if (!mid || !meshIndex[mid]) return false;
      if (!(p.w > 0 && p.d > 0 && p.h > 0)) return false;
      if (p.w < plan.wRange[0] || p.w > plan.wRange[1]) return false;
      if (!p.price || p.price < 1000) return false;
      if (seen.has(mid)) return false;
      seen.add(mid);
      return true;
    })
    .sort((a, b) => a.price - b.price || String(a.sid).localeCompare(String(b.sid)));
}

/**
 * Отбор «база + 3»: берём равномерно по цене (дешёвый → дорогой), но не два подряд из одного
 * магазина и одного стиля, если есть выбор. Последний — самый дорогой (premium).
 */
function pickSpread(list, take) {
  if (list.length <= take) return list;
  const out = [];
  const step = (list.length - 1) / (take - 1);
  for (let i = 0; i < take; i += 1) {
    let idx = Math.round(i * step);
    let guard = 0;
    while (guard < list.length) {
      const c = list[idx];
      const prev = out[out.length - 1];
      const clash = prev && (prev.shop === c.shop || prev.style === c.style) && out.length < take;
      if (!out.includes(c) && (!clash || guard > 6)) break;
      idx = (idx + 1) % list.length;
      guard += 1;
    }
    if (!out.includes(list[idx])) out.push(list[idx]);
  }
  return out.slice(0, take);
}

async function main() {
  const demo = JSON.parse(readFileSync(DEMO, "utf8"));
  const feeds = demo.feeds || {};
  const meshIndex = await fetchJson(`${MESH_BASE}mesh-index.json`);
  let orient = {};
  try {
    orient = await fetchJson(`${MESH_BASE}orient.json`);
  } catch {
    orient = {}; // без ориентации мебель встанет с yaw=0 — как в демо
  }

  const options = [];
  const report = [];
  for (const plan of ROLE_PLAN) {
    const feed = feeds[plan.role] || [];
    const list = candidates(feed, meshIndex, plan);
    const picked = pickSpread(list, plan.take);
    picked.forEach((p, i) => {
      const meshId = p.msid || p.sid;
      const o = orient[meshId] || {};
      options.push({
        id: `${plan.key}-${i + 1}`,
        slotKey: plan.key,
        category: plan.category,
        titleRu: p.name,
        titleEn: `${EN_ROLE[plan.role] ?? plan.key} · ${p.shop}`,
        descRu: `${p.w}×${p.d}×${p.h} см · ${p.shop}`,
        tier: TIER_BY_INDEX[i] ?? "standard",
        priceGbp: i === 0 ? 0 : gbp(p.price),
        listPriceGbp: gbp(p.price),
        availability: "available",
        asset: {
          kind: "mesh",
          meshId,
          yawDeg: Number(o.yaw || 0),
          wCm: p.w,
          dCm: p.d,
          hCm: p.h,
        },
        previewUrl: p.img ? DEMO_IMG_BASE + p.img : undefined,
        sourceUrl: p.url,
        shop: p.shop,
        style: p.style,
      });
    });
    report.push(`${plan.role}: лента ${feed.length} → годных ${list.length} → взято ${picked.length}`);
  }

  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(
    OUT,
    `${JSON.stringify(
      {
        _about: "Мебель конфигуратора из лент /demo/. Собрано tools/flat3d/build-catalogue.mjs — руками не править.",
        generatedAt: new Date().toISOString().slice(0, 10),
        rubPerGbp: RUB_PER_GBP,
        options,
      },
      null,
      1,
    )}\n`,
  );
  console.log(report.join("\n"));
  console.log(`\nитого опций: ${options.length} → ${OUT}`);
}

main().catch((e) => {
  console.error("сборка каталога не удалась:", e.message);
  process.exit(1);
});
