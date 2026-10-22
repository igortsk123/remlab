#!/usr/bin/env node
// ОТЧЁТ ЛЕНТ ЗАМЕН ПО СТИЛЮ И РОЛИ (план demo-18 п.1) — строкой в журнал сборки витрины. Считает ТЕМ ЖЕ правилом, что мост в /flat
// и тест 2.20 (`lib/configurator/demo-feeds.ts`, node сам снимает типы): на месте каждого предмета ядра в каждом варианте —
//   eligible_sku           сколько товаров ленты стиля годится месту (модель, фото, размеры, та же форма дивана, не текущий);
//   unique_msid            сколько среди них разных моделей;
//   published_alternatives сколько вариантов получит полоса выбора /flat (до `FEED_LIMIT`, без текущего).
// Зовёт сборка демо (`tools/scout/flat215_demo.py`) после записи данных; меньше `mesh_target` (10, `rules/demo-swap.json`,
// владелец 22.10 TG 793) — пометка «!». Жёсткий гейт live-теста 2.20 остаётся ≥ 5 (`e2e/live/flat-rooms.live.ts`): недобор до 10
// по нехватке каталога ведёт и добирает `tools/scout/demo_band.py`, а не красный тест.
//   node tools/flat3d/swap-report.mjs <demo-data.json> [--json]
import { readFileSync } from "node:fs";

import { alternatives, candidates, feedForStyle, placeOf } from "../../lib/configurator/demo-feeds.ts";

// роли ядра, у которых /flat даёт ленту замен; ковёр — плита с фото, длинная сторона не короче дивана (demo-18 п.2, `placeOf`)
const ROLES = ["диван", "столик", "тв-тумба", "торшер", "стол обеденный", "ковёр"];
const NEED = JSON.parse(readFileSync(new URL("../scout/rules/demo-swap.json", import.meta.url), "utf8")).mesh_target;

export function swapReport(data) {
  const rows = [];
  for (const v of data.variants ?? []) {
    for (const role of ROLES) {
      const it = (v.items ?? []).find((i) => i.role === role);
      if (!it) continue;
      const feed = feedForStyle(data.feeds?.[role] ?? [], v.style);
      const place = placeOf(it, v.items ?? []);
      const exclude = new Set([it.sku?.sid ?? "", it.sku?.name ?? ""]);
      const all = candidates(feed, place, exclude);
      rows.push({ variant: v.id, style: v.style, role, eligible_sku: all.length, unique_msid: new Set(all.map((p) => p.msid)).size,
        published_alternatives: alternatives(feed, place, exclude).length });
    }
  }
  return rows;
}

const file = process.argv[2];
if (file) {
  const rows = swapReport(JSON.parse(readFileSync(file, "utf8")));
  if (process.argv.includes("--json")) console.log(JSON.stringify(rows));
  else {
    for (const r of rows) {
      console.log(`ленты замен: ${r.style} ${r.role}: eligible_sku ${r.eligible_sku}, unique_msid ${r.unique_msid}, `
        + `published_alternatives ${r.published_alternatives}${r.published_alternatives < NEED ? ` ! меньше ${NEED}` : ""}`);
    }
  }
}
