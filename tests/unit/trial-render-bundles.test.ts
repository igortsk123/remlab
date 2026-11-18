import { describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { reduceSource } from "@/lib/trial/repo-render";

// Заказ рендера из тура по `msid`+`name` на НАСТОЯЩИХ опубликованных данных туров (T-20261117-20/3). Файлы лежат вне репозитория — тест идёт, только когда
// задан `REAL_BUNDLES` (пути через «:»), иначе пропущен (CI без них). Весь путь: страница шлёт заказ → `reduceSource` (приложение) → `render_snapshot.py --canon`
// (сервис кадров) — те же две половины, что в проде; нужен `python3`. Запуск: `REAL_BUNDLES=a.json:b.json pnpm exec vitest run tests/unit/trial-render-bundles.test.ts`.
const FILES = (process.env.REAL_BUNDLES ?? "").split(":").filter(Boolean);
type Dict = Record<string, unknown>;
const isDict = (v: unknown): v is Dict => typeof v === "object" && v !== null && !Array.isArray(v);
const SCRIPT = path.join(process.cwd(), "tools/scout/render_snapshot.py");

function cards(v: unknown, out: Dict[]): void {
  if (Array.isArray(v)) { for (const x of v) cards(x, out); return; }
  if (!isDict(v)) return;
  if (typeof v.name === "string" && "msid" in v && v.sid == null) out.push(v);
  for (const x of Object.values(v)) cards(x, out);
}

function canon(dir: string, source: Dict, req: Dict): { ok: boolean; code?: string; scene_hash?: string } {
  const a = path.join(dir, "src.json"), b = path.join(dir, "req.json");
  writeFileSync(a, JSON.stringify(source)); writeFileSync(b, JSON.stringify(req));
  const r = spawnSync("python3", ["-I", SCRIPT, "--canon", a, b], { encoding: "utf8" });
  if (r.status !== 0) throw new Error(`python: ${r.stderr}`);
  return JSON.parse(r.stdout.trim().split("\n").pop() ?? "{}");
}

describe.skipIf(FILES.length === 0)("рендер из тура: настоящие данные туров, ключ товара (msid, name)", () => {
  for (const f of FILES) {
    const json = readFileSync(f, "utf8"), bundle = JSON.parse(json) as Dict;
    const variants = (Array.isArray(bundle.variants) ? bundle.variants : []).filter(isDict);
    const dir = mkdtempSync(path.join(tmpdir(), "trial-bundle-"));
    let checked = 0;
    it(`${path.basename(path.dirname(f))}/${path.basename(f)}: каждый вариант принимается как есть и по предметам из msid+name, тот же хеш`, () => {
      if (variants.length === 0) return;                                   // бандл без вариантов (комната не обставлена) — проверять нечего
      for (const v of variants) {
        const items = (Array.isArray(v.items) ? v.items : []).filter(isDict).map((i) => {
          const k = i.sku as Dict;
          return { role: String(i.role), ...(k.msid ? { msid: String(k.msid) } : {}), name: String(k.name), x: i.x, y: i.y, rot: i.rot ?? 0, corner: !!i.corner, corner_left: !!i.corner_left, section: i.section ?? null };
        });
        if (items.length === 0) continue;
        // у бандла-образца старого вида ракурсов в варианте нет — подставляем две позы внутри комнаты (позы в этой проверке не предмет)
        const room = (isDict(bundle.rooms_geo) && isDict((bundle.rooms_geo as Dict)[String(v.room_id ?? "living")]) ? (bundle.rooms_geo as Dict)[String(v.room_id ?? "living")] : bundle.room) as { w: number; d: number };
        const cams = [{ name: "C1", x: 20, y: 20, rot: 45, fov: 90 }, { name: "C2", x: room.w - 20, y: room.d - 20, rot: 225, fov: 90 }];
        const base = { v: 1, variant_id: String(v.id), room_id: String(v.room_id ?? "living"), cams };
        checked += 1;
        const src = reduceSource(json, { ...base, items } as never)!;
        expect(JSON.stringify(src)).not.toContain('"sid"');
        const dflt = canon(dir, src, base), byKey = canon(dir, src, { ...base, items });
        expect(dflt, `вариант ${String(v.id)} как есть (${JSON.stringify(dflt)})`).toMatchObject({ ok: true });
        expect(byKey, `вариант ${String(v.id)} по msid+name (${JSON.stringify(byKey)})`).toMatchObject({ ok: true });
        expect(byKey.scene_hash).toBe(dflt.scene_hash);
      }
      if (variants.some((v) => Array.isArray(v.items) && v.items.length > 0)) expect(checked).toBeGreaterThan(0);
      console.log(`${path.basename(f)}: проверено вариантов ${checked} из ${variants.length}`);
    }, 120_000);
    it(`${path.basename(path.dirname(f))}/${path.basename(f)}: любая карточка данных как замена — не «bad_item» (пары однозначны)`, () => {
      const all: Dict[] = []; cards(bundle, all);
      const v = variants.find((x) => Array.isArray(x.items) && x.items.length > 0);
      if (!v) return;
      const first = (v.items as Dict[]).filter(isDict)[0]!;
      const seen = new Set<string>(); const bad: string[] = [];
      for (const c of all) {
        const key = `${String(c.msid ?? "")}\u0000${String(c.name)}`;
        if (seen.has(key)) continue; seen.add(key);
        const items = [{ role: String(first.role), ...(c.msid ? { msid: String(c.msid) } : {}), name: String(c.name), x: first.x, y: first.y, rot: 0 }];
        const base = { v: 1, variant_id: String(v.id), room_id: String(v.room_id ?? "living"), items };
        const r = canon(dir, reduceSource(json, base as never)!, base);
        if (!r.ok && r.code === "bad_item") bad.push(key.replace("\u0000", " | "));
      }
      expect(bad).toEqual([]);
    }, 300_000);
  }
});
