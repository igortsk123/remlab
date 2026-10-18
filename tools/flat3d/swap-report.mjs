#!/usr/bin/env node
// ОТЧЁТ ЛЕНТ ЗАМЕН ПО СТИЛЮ И РОЛИ (план demo-18 п.1) — строкой в журнал сборки витрины. Считает ТЕМ ЖЕ правилом, что мост в /flat
// и тест 2.20 (`lib/configurator/demo-feeds.ts`, node сам снимает типы): на месте каждого предмета ядра в каждом варианте —
//   eligible_sku           сколько товаров ленты стиля годится месту (модель, фото, размеры, та же форма дивана, не текущий);
//   unique_msid            сколько среди них разных моделей;
//   published_alternatives сколько вариантов получит полоса выбора /flat (до `FEED_LIMIT`, без текущего).
// Зовёт сборка демо (`tools/scout/flat215_demo.py`) после записи данных; меньше 5 — пометка «!» (норма карты 2.20).
//   node tools/flat3d/swap-report.mjs <demo-data.json> [--json]
import { readFileSync } from "node:fs";

import { alternatives, candidates, feedForStyle } from "../../lib/configurator/demo-feeds.ts";

// роли ядра, у которых /flat даёт ленту замен (ковёр — плита с фото, своя лента — demo-18 п.2)
const ROLES = ["диван", "столик", "тв-тумба", "торшер", "стол обеденный"];
const NEED = 5;

export function swapReport(data) {
  const rows = [];
  for (const v of data.variants ?? []) {
    for (const role of ROLES) {
      const it = (v.items ?? []).find((i) => i.role === role);
      if (!it) continue;
      const feed = feedForStyle(data.feeds?.[role] ?? [], v.style);
      const place = { w: it.w ?? 0, d: it.d ?? 0, model: it.sku?.msid, corner: !!it.corner, cornerLeft: !!it.corner_left };
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
