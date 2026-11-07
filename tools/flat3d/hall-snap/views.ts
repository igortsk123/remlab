// ПОДБОР ДВУХ ВИДОВ ПРИХОЖЕЙ (T-20261106-73, ведущий 06.11). Правило — данными: `tools/scout/rules/hall-views.json` (что обязано
// быть в кадре каждого вида, зазор до глаза, допуск среза). Камера и близость — функции блока CAMFIT страницы демо
// (`tools/scout/flat215-demo/index.html`: `camProj`, `camNear`), исполненные тем же способом, что `tools/flat3d/demo-cams.mjs`, —
// без копии и без правки страницы. Своё здесь только проверка «не заслонён» лучами по лицу предмета с его высотой подвеса (`elev`);
// проекция и маска CAMFIT подвес знают сами с T-20261107-05/4 (`camElev`) — в `camProj` высоты передаются от низа предмета.
// Сейчас подбор читает стенд снимков (`tools/flat3d/hall-snap.mjs`); на этапе 6 плана hall-demo-01 он станет источником
// `CAM_ZONES.hall` (лог плана), а не параллельной логикой.

export interface HallItem { role: string; x: number; y: number; rot: number; w: number; d: number; h: number; elev?: number }
export interface HallRoom { w: number; d: number; openings?: unknown[]; height_cm?: number }
export interface HallPose { x: number; y: number; rot: number; fov: number; pose: number }

/** Что обязано быть в кадре: роли или группа хранения; `whole` — целиком и не заслонено на `vis_min`, иначе доля в кадре и доля
 *  не заслонённого — обе не меньше `min`; `face_deg` — лицом к камере: луч на центр лица не дальше этого угла от нормали
 *  (зеркало «полоской» на боковой стене формально целиком, но не видно). */
interface Need { roles?: string[]; group?: "any_storage" | "main_storage"; whole?: boolean; min?: number; face_deg?: number }
export interface HallViewsRule {
  fovs: number[]; clear_cm: number; cut_max: number; sliver: number; whole_margin: number; vis_min: number; shown_min: number;
  grid_cm: number; rot_step: number; apart: { deg: number; near_deg: number; near_cm: number };
  storage: { main: string[]; near: string[] };
  views: { id: string; label: string; need: Need[]; prefer: Need[] }[];
}

type Box = { x0: number; x1: number; y0: number; y1: number; behind: number } | null;
type CamIt = { x: number; y: number; w: number; d: number; rot: number };
type Cam = { x: number; y: number; rot: number; fov: number };
type Stats = { empty: number; ceil: number };
export interface Camfit {
  proj: (c: Cam, it: CamIt, h0: number, h1: number) => Box; near: (c: Cam, it: CamIt) => number;
  /** метрики кадра страницы (`camStats`) и штраф пустого вида зоны (`camMorePen`: пустая стена и потолок) */
  stats: (c: Cam, its: CamIt[], W: number, H: number, o?: { w?: number }) => Stats; morePen: (s: Stats) => number;
  aspect: number; shift: number; eye: number;
}

/** Функции CAMFIT из текста блока страницы (`// CAMFIT START` … `// CAMFIT END`). Комната — как `D.room` у `demo-cams.mjs`. */
export function camfitFrom(block: string, room: HallRoom): Camfit {
  const api = new Function("D", `${block};return {camProj,camNear,camStats,camMorePen,CAM_ASPECT,CAM_SHIFT_N,CAM_EYE};`)({ room }) as {
    camProj: Camfit["proj"]; camNear: Camfit["near"]; camStats: Camfit["stats"]; camMorePen: Camfit["morePen"];
    CAM_ASPECT: number; CAM_SHIFT_N: number; CAM_EYE: number };
  return { proj: api.camProj, near: api.camNear, stats: api.camStats, morePen: api.camMorePen, aspect: api.CAM_ASPECT,
    shift: api.CAM_SHIFT_N, eye: api.CAM_EYE };
}

const base = (r: string): string => r.replace(/\s+\d+$/, "").trim();
const z0Of = (it: HallItem): number => it.elev ?? 0;

/**
 * Рамка предмета в кадре пропорции `aspect`. CAMFIT считает кадр /demo (2048×1489); по горизонтали объектив тот же, а по вертикали
 * экранная координата растягивается в aspect/CAM_ASPECT раз вокруг сдвига объектива (сдвиг позы v2 одинаков при пропорции ≥ 1,5 —
 * `viewer.ts:photoShift`). Пересчёт результата, а не своя проекция.
 */
function frameBox(cf: Camfit, c: Cam, it: HallItem, aspect: number): Box {
  const b = cf.proj(c, it, 0, it.h);   // высоты от низа предмета: подвес `elev` CAMFIT добавляет сам (`camElev`, T-20261107-05/4)
  if (!b) return null;
  const k = aspect / cf.aspect, s = (y: number) => (y - cf.shift) * k + cf.shift;
  return { x0: b.x0, x1: b.x1, y0: s(b.y0), y1: s(b.y1), behind: b.behind };
}

/** Доля коробки предмета в кадре (0…1); углы за спиной уменьшают долю (коробка за ними не построена). */
function inFrame(b: Box): number {
  if (!b) return 0;
  const a = (b.x1 - b.x0) * (b.y1 - b.y0);
  if (a <= 0) return 0;
  const f = (Math.max(0, Math.min(b.x1, 1) - Math.max(b.x0, -1)) * Math.max(0, Math.min(b.y1, 1) - Math.max(b.y0, -1))) / a;
  return f * (1 - b.behind / 8);
}

const whole = (b: Box, m: number): boolean => !!b && !b.behind && b.x0 >= -1 + m && b.x1 <= 1 - m && b.y0 >= -1 + m && b.y1 <= 1 - m;

/** Отрезок глаз → точка пересекает коробку предмета (след Ш×Г с поворотом, высота от подвеса)? */
function hits(e: [number, number, number], p: [number, number, number], it: HallItem): boolean {
  const a = (it.rot * Math.PI) / 180, u = [Math.cos(a), -Math.sin(a)], n = [Math.sin(a), Math.cos(a)];
  const loc = (q: [number, number, number]) => { const dx = q[0] - it.x, dy = q[1] - it.y; return [dx * u[0]! + dy * u[1]!, dx * n[0]! + dy * n[1]!, q[2]]; };
  const A = loc(e), B = loc(p), lo = [-it.w / 2, -it.d / 2, z0Of(it)], hi = [it.w / 2, it.d / 2, z0Of(it) + it.h];
  let t0 = 1e-3, t1 = 1 - 1e-3;
  for (let k = 0; k < 3; k++) {
    const d = B[k]! - A[k]!;
    if (Math.abs(d) < 1e-9) { if (A[k]! < lo[k]! || A[k]! > hi[k]!) return false; continue; }
    let s0 = (lo[k]! - A[k]!) / d, s1 = (hi[k]! - A[k]!) / d;
    if (s0 > s1) [s0, s1] = [s1, s0];
    t0 = Math.max(t0, s0); t1 = Math.min(t1, s1);
    if (t0 > t1) return false;
  }
  return true;
}

/** Доля лицевой стороны предмета (5×5 точек, с высотой подвеса), которую не закрывают другие предметы. */
function visible(c: Cam, eye: number, it: HallItem, all: HallItem[]): number {
  const a = (it.rot * Math.PI) / 180, u = [Math.cos(a), -Math.sin(a)], n = [Math.sin(a), Math.cos(a)];
  const e: [number, number, number] = [c.x, c.y, eye], others = all.filter((o) => o !== it);
  let ok = 0;
  for (let i = 0; i < 5; i++) for (let j = 0; j < 5; j++) {
    const s = ((i + 0.5) / 5 - 0.5) * it.w * 0.9, z = z0Of(it) + ((j + 0.5) / 5) * it.h;
    const p: [number, number, number] = [it.x + u[0]! * s + n[0]! * (it.d / 2 + 0.5), it.y + u[1]! * s + n[1]! * (it.d / 2 + 0.5), z];
    if (!others.some((o) => hits(e, p, o))) ok++;
  }
  return ok / 25;
}

/** Лицо предмета повёрнуто к камере не дальше `deg`° (нет `deg` — без условия). */
function facing(c: Cam, it: HallItem, deg?: number): boolean {
  if (deg == null) return true;
  const a = (it.rot * Math.PI) / 180, nx = Math.sin(a), ny = Math.cos(a);
  const fx = it.x + nx * (it.d / 2), fy = it.y + ny * (it.d / 2), dx = c.x - fx, dy = c.y - fy, l = Math.hypot(dx, dy) || 1;
  return (dx * nx + dy * ny) / l >= Math.cos((deg * Math.PI) / 180);
}

export interface ViewPick {
  id: string; label: string; ok: boolean; pose: HallPose;
  need: { want: string; got: string | null; inFrame: number; visible: number }[];
  prefer: { want: string; got: string | null }[];
  nearestCm: number; shown: string[]; cut: string[]; why: string[]; quality?: number;
}

/** Главное хранение набора: первая роль `main`; нет — самый крупный по объёму предмет `near`. */
function mainStorage(rule: HallViewsRule, its: HallItem[]): HallItem[] {
  for (const r of rule.storage.main) { const m = its.filter((it) => base(it.role) === r); if (m.length) return m; }
  const near = its.filter((it) => rule.storage.near.includes(base(it.role)));
  return near.length ? [near.reduce((a, b) => (b.w * b.d * b.h > a.w * a.d * a.h ? b : a))] : [];
}
function candidates(rule: HallViewsRule, its: HallItem[], nd: Need): HallItem[] {
  if (nd.roles) return its.filter((it) => nd.roles!.includes(base(it.role)));
  if (nd.group === "main_storage") return mainStorage(rule, its);
  return its.filter((it) => [...rule.storage.main, ...rule.storage.near].includes(base(it.role)));
}
const label = (nd: Need): string => nd.roles?.join("|") ?? nd.group ?? "?";

interface Eval { pose: HallPose; valid: boolean; hardOk: boolean; needOk: number; preferOk: number; shown: string[]; area: number; quality: number; pick: ViewPick }

function evaluate(cf: Camfit, rule: HallViewsRule, roomW: number, roomD: number, its: HallItem[], view: HallViewsRule["views"][number], c: Cam, aspect: number): Eval {
  const why: string[] = [], cut: string[] = [], shown: string[] = [];
  let nearest = 1e9;
  const boxes = new Map<HallItem, Box>();
  for (const it of its) {
    const nr = cf.near(c, it); nearest = Math.min(nearest, nr);
    if (nr < rule.clear_cm) why.push(`${it.role} ближе ${rule.clear_cm} см (${Math.round(nr)})`);
    const b = frameBox(cf, c, it, aspect); boxes.set(it, b);
    const f = inFrame(b);
    if (f > rule.sliver && f < 1 - rule.cut_max) cut.push(`${it.role} ${Math.round(f * 100)} %`);
    if (f >= rule.shown_min) shown.push(it.role);
  }
  if (cut.length) why.push(`срезано больше чем наполовину: ${cut.join(", ")}`);
  let area = 0;
  const check = (nd: Need) => {
    let best: { it: HallItem; f: number; v: number } | null = null;
    for (const it of candidates(rule, its, nd)) {
      const b = boxes.get(it)!, f = inFrame(b);
      const framed = (nd.whole ? whole(b, rule.whole_margin) : f >= (nd.min ?? rule.shown_min)) && facing(c, it, nd.face_deg);
      if (!framed) { if (!best || f > best.f) best = { it, f, v: 0 }; continue; }
      const v = visible(c, cf.eye, it, its);
      if (v >= (nd.whole ? rule.vis_min : (nd.min ?? rule.shown_min))) { area += (Math.min(b!.x1, 1) - Math.max(b!.x0, -1)) * (Math.min(b!.y1, 1) - Math.max(b!.y0, -1)); return { it, f, v, ok: true }; }
      if (!best || f > best.f) best = { it, f, v };
    }
    return best ? { ...best, ok: false } : null;
  };
  const need = view.need.map((nd) => { const r = check(nd); return { nd, r }; });
  const prefer = view.prefer.map((nd) => { const r = check(nd); return { nd, r }; });
  const needOk = need.filter((x) => x.r?.ok).length;
  need.forEach((x) => { if (!x.r?.ok) why.push(`${label(x.nd)}: ${x.nd.whole ? "не целиком или заслонено" : "мало в кадре или заслонено"}`); });
  const pose: HallPose = { x: Math.round(c.x), y: Math.round(c.y), rot: Math.round(c.rot) % 360, fov: c.fov, pose: 2 };
  const pick: ViewPick = {
    id: view.id, label: view.label, ok: !why.length, pose,
    need: need.map((x) => ({ want: label(x.nd), got: x.r?.it.role ?? null, inFrame: round2(x.r?.f ?? 0), visible: round2(x.r?.v ?? 0) })),
    prefer: prefer.map((x) => ({ want: label(x.nd), got: x.r?.ok ? x.r.it.role : null })),
    nearestCm: Math.round(nearest), shown, cut, why,
  };
  // качество годного вида: показанная мебель + размер обязательного в кадре − штраф пустой стены и потолка страницы (`camMorePen`,
  // маска 48 столбцов; маска CAMFIT — кадр /demo, предмет — коробка от пола: для «пустых столбцов» этого хватает)
  const quality = !why.length ? shown.length + area - cf.morePen(cf.stats(c, its, roomW, roomD, { w: 48 })) : -1e9;
  pick.quality = Math.round(quality * 100) / 100;
  return { pose, quality, valid: !why.length, hardOk: nearest >= rule.clear_cm && !cut.length, needOk, preferOk: prefer.filter((x) => x.r?.ok).length, shown, area, pick };
}
const round2 = (v: number): number => Math.round(v * 100) / 100;

const angle = (a: number, b: number): number => Math.abs((((a - b) % 360) + 540) % 360 - 180);

/**
 * Два вида по правилу: перебор точек сетки `grid_cm` (не ближе `clear_cm` к стенам), направлений шагом `rot_step` и объективов `fovs`. Годен вид,
 * где всё обязательное целиком и не заслонено, ничего не ближе `clear_cm` и нет среза больше `cut_max`. Из годных — больше
 * желательного, затем качество: показанная мебель, размер обязательного, минус пустая стена и потолок (`camMorePen` страницы). Вид 2 — в другую сторону (`apart`). Годного нет — лучший
 * по числу выполненного с `ok: false` и причинами (не молча).
 */
export function pickHallViews(cf: Camfit, rule: HallViewsRule, room: HallRoom, its: HallItem[], aspect: number): ViewPick[] {
  const out: Eval[] = [];
  for (const view of rule.views) {
    let best: Eval | null = null;
    // объектив — стадиями (`fovs`): первая стадия, где есть годный вид; иначе лучший по всем стадиям
    for (const fov of rule.fovs) {
      if (best?.valid) break;
      for (let x = rule.clear_cm; x <= room.w - rule.clear_cm + 1e-9; x += rule.grid_cm)
      for (let y = rule.clear_cm; y <= room.d - rule.clear_cm + 1e-9; y += rule.grid_cm)
        for (let rot = 0; rot < 360; rot += rule.rot_step) {
          const c = { x, y, rot, fov };
          if (out.some((o) => !apartOk(rule, o.pose, c))) continue;
          const e = evaluate(cf, rule, room.w, room.d, its, view, c, aspect);
          if (!best || better(e, best)) best = e;
        }
    }
    out.push(best!);
  }
  return out.map((e) => e.pick);
}

function apartOk(rule: HallViewsRule, a: HallPose, b: Cam): boolean {
  const ang = angle(a.rot, b.rot);
  return ang >= rule.apart.deg || (ang >= rule.apart.near_deg && Math.hypot(a.x - b.x, a.y - b.y) >= rule.apart.near_cm);
}

function better(a: Eval, b: Eval): boolean {
  // годный → без нарушений зазора и среза → больше обязательного → желательного → качество кадра (мебель, размер, пустое)
  const key = (e: Eval) => [e.valid ? 1 : 0, e.hardOk ? 1 : 0, e.needOk, e.preferOk, e.quality, e.shown.length];
  const ka = key(a), kb = key(b);
  for (let i = 0; i < ka.length; i++) if (ka[i] !== kb[i]) return ka[i]! > kb[i]!;
  return false;
}
