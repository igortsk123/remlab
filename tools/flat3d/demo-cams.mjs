#!/usr/bin/env node
// РАКУРСЫ ОКНА ВАРИАНТА — В ДАННЫЕ ВИТРИНЫ (план demo-05 п.8). Окно демо выбирает два ракурса правилами страницы (блок
// CAMFIT в `tools/scout/flat215-demo/index.html`, `camPair`), а /flat их не знал — режим «Фото» там был пустым текстом.
// Скрипт исполняет ТОТ ЖЕ блок страницы по каждому варианту и пишет `v.cams = [C1, C2]` (+ `v.cam_level`) в demo-data.json:
// одна функция — один выбор для окна и для /flat. Зовёт сборка демо (`flat215_demo.py`) перед записью данных.
// С demo-22 у каждого вида — окно превью `crop[<пропорция>] = {x,y,w,h,keep}` (доли кадра) и у варианта — отчёт покрытия
// `cam_cover` (что из мебели не видно ни в одном виде и почему); тот же отчёт печатается в лог сборки.
// ОДНА ПАРА НА ВСЕ СТИЛИ (demo-31, владелец 02.11): данные с одной расстановкой на все варианты (`D.one_layout`, ставит
// `flat215_demo.py`) — пара подбирается ОДИН раз по мебели всех вариантов (`camPairAll`: точка годна, если чиста в каждом, ключ —
// худший), у всех вариантов те же точки (x, y, rot, fov); окно превью и сдвиг телефона — по мебели своего варианта. Ставит
// `D.cams_shared` — страница по нему не пересчитывает точки после замены товара (`index.html:defaultCams`).
// Исключение — комната с меткой геометрии `cams_own` (своя расстановка у каждого стиля, T-20261107-05/4): пара — по мебели своего стиля.
//   node tools/flat3d/demo-cams.mjs <demo-data.json>        дописать ракурсы на месте
import { readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const html = readFileSync(join(ROOT, "tools/scout/flat215-demo/index.html"), "utf8");
const block = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const file = process.argv[2];
if (!file) {
  console.error("нужен путь к demo-data.json");
  process.exit(2);
}
const D = JSON.parse(readFileSync(file, "utf8"));
// КОМНАТА ВАРИАНТА (onb-07 основа, ADR-0330 п.3): точки подбираются в геометрии комнаты варианта — `D.rooms_geo[v.room_id]`,
// правило то же, что `index.html:roomGeoOf`: нет `rooms_geo` или вариант гостиной — `D.room`; комнаты нет в данных — вариант пропускаем
const roomIdOf = (v) => String(v.room_id || "living");
const geoOf = (v) => D.rooms_geo?.[roomIdOf(v)] ?? (roomIdOf(v) === "living" || !D.rooms_geo ? D.room : null);
const p = 3; // как `camPad()` страницы и клэмп сервера
let n = 0;
const vars = D.variants ?? [];
const itsOf = (v) => (v.items ?? []).map((it) => ({ ...it, x: +it.x, y: +it.y, w: +it.w, d: +it.d, rot: +it.rot || 0 }));
// прежняя пара варианта — last-known-good правила видов v2 (`camPairV2` `opt.prev`)
const prevOf = (v) => (Array.isArray(v.cams) && v.cams.length === 2 ? v.cams.map((c) => ({ ...c })) : null);
// по комнатам в порядке вариантов; одна пара на все стили (demo-31) — внутри своей комнаты
const groups = new Map();
for (const v of vars) {
  const geo = geoOf(v);
  if (!geo) { console.log(`WARN:demo_cams: ${v.id} — комнаты ${roomIdOf(v)} нет в rooms_geo, ракурсы не подобраны`); continue; }
  const k = roomIdOf(v);
  if (!groups.has(k)) groups.set(k, { geo, list: [] });
  groups.get(k).list.push(v);
}
D.cams_shared = false;
for (const [rid, { geo, list }] of groups) {
// блок страницы читает D.room (двери для правила «не у двери», высота потолка) — отдаём комнату этой группы вариантов
const api = new Function("D", `${block}\n;return {camPair, camPairAll, camAng, camZ, camLiveBigCut, camIsMain, camRole};`)({ ...D, room: geo });
const W = geo.w;
const H = geo.d;
const corners = [{ x: p, y: p }, { x: W - p, y: p }, { x: W - p, y: H - p }, { x: p, y: H - p }];
// своя расстановка у каждого стиля (`geo.cams_own`, сборка — `flat215_demo.room_variants`, T-20261107-05/4: прихожая) — пара на стиль
const shared = !!D.one_layout && list.length > 1 && !geo.cams_own;
// мебель стиля — один массив на комнату, покрытие точки при ней — один раз (`cvc`, T-20261107-47/2): подбор по стилю (ниже, «с двух
// концов») берёт его готовым из общего подбора; точки и выбор те же, данные побайтно те же
const IT = list.map(itsOf), cvc = new Map();
let all = shared ? api.camPairAll(IT, W, H, corners, { cvc, prev: prevOf(list[0]) }) : null;
if (shared) console.log(`${rid === "living" ? "" : `${rid}: `}одна пара на ${list.length} вариантов: ${all.how}`);
// СТИЛЬ НА ЗАПАСНОМ НЕ ПОРТИТ ПОКРЫТИЕ ОСТАЛЬНЫХ (T-20261107-11/3, ведущий): неоклассика на запасном нейтральном ковре
// (`fill[].rug_universal`, T-11/2) сдвинула общую пару, и сканди, современный и минимализм потеряли торшер. Ключ пары — худший по
// вариантам, поэтому новый стиль с заслонённым торшером тянул всех. Правило: покрытие каждого стиля со своим набором — не хуже, чем у
// пары без стилей на запасном. Хуже — ищем одну пару с этим условием (`camPairAll` `opt.keep`); нет такой — стили на запасном
// получают свою пару (одна точка на все стили, demo-31, у них нарушается — громко WARN). Стилей на запасном нет или общая пара
// никого не ухудшила — как было
const onSpare = (v) => (v.fill ?? []).some((x) => x.rug_universal);
let perOf = (vi) => all?.per?.[vi];
if (shared && list.some(onSpare) && list.some((v) => !onSpare(v))) {
  const P = list.filter((v) => !onSpare(v)), S = list.filter(onSpare);
  const base = api.camPairAll(P.map(itsOf), W, H, corners);
  const keep = list.map((v) => (onSpare(v) ? 0 : base.per[P.indexOf(v)].bits));
  const worse = list.filter((v, vi) => keep[vi] && (all.per[vi].bits & keep[vi]) !== keep[vi]).map((v) => v.style || v.id);
  if (worse.length) {
    const kept = api.camPairAll(list.map(itsOf), W, H, corners, { keep });
    if (kept) {
      all = kept;
      perOf = (vi) => all.per[vi];
      console.log(`одна пара хуже для ${worse.join(", ")} — взята пара, где их покрытие не хуже, чем без стилей на запасном: ${all.how}`);
    } else {
      const own = api.camPairAll(S.map(itsOf), W, H, corners);
      all = base;
      perOf = (vi) => (onSpare(list[vi]) ? { ...own, ...own.per[S.indexOf(list[vi])] } : base.per[P.indexOf(list[vi])]);
      console.log(`WARN:demo_cams: ${rid} — одной пары без ухудшения ${worse.join(", ")} нет: стили на запасном (${S.map((v) => v.style || v.id).join(", ")}) со своей парой: ${own.how}`);
    }
  }
}
// ПРАВИЛО ВИДОВ v2 (T-20261108-73/4, владелец TG 668/671; `camPairV2`): вид 1 — со стороны двери, вид 2 — по смыслу комнаты.
// Общая пара на все стили не вышла строго (`relax` > 0 — ступень лестницы ослаблений) — у стиля своя пара, если её ступень ниже,
// а при той же ступени — если её виды лучше по ключу (смысл видов важнее одной точки на все стили, как «с двух концов» до v2). Прежняя пара варианта — last-known-good (`opt.prev`):
// смысл видов не выполнить — она, а не случайная
const v2 =shared && all && all.relax != null;
if (v2 && all.relax > 0) {
  const own = list.map((v, vi) => api.camPairAll([IT[vi]], W, H, corners, { prev: prevOf(v) }));
  // та же ступень — своя, если ключ видов (`keys`: обязательное, его недобор, крупные срезы, масса, недобор доли; сумма C1 + C2) лучше
  const sc = (o) => [o.relax, ...[0, 1, 2, 3, 4].map((i) => (o.keys ?? []).reduce((a, k) => a + (k[i] ?? 0), 0))];
  const less = (a, b) => { for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] < b[i]; return false; };
  const take = own.map((o) => !!o && o.relax != null && !!o.keys && less(sc(o), sc(all)));
  if (take.some(Boolean)) {
    const shPer = perOf;
    perOf = (vi) => (take[vi] ? { ...own[vi], ...own[vi].per[0] } : shPer(vi));
    console.log(`${rid}: общая пара — ступень ${all.relax}; своя пара лучше у стилей ${list.filter((_, vi) => take[vi]).map((v) => `${v.style || v.id} (${own[list.indexOf(v)].relax})`).join(", ")}`);
  }
}
// ЧИСТАЯ ОБЛОЖКА И ВИДЫ ЗОНЫ ВАЖНЕЕ ОДНОЙ ПАРЫ (T-20261107-67; только прежний подбор `camPairAll0` — зоны без `intent`, кухня):
// у стиля — своя пара, если она не хуже общей по обязательному покрытию (`mm`) и видам зоны и лучше по ним или по обложке
if (shared && !v2 && (all.zoneMiss || all.posterCut)) {
  const own = list.map((v, vi) => api.camPairAll([IT[vi]], W, H, corners, { cvc }));
  const pc =(p) => p.posterCut ?? 0, mm = (p) => p.mm ?? 0;
  const take = own.map((o) => !!o && !o.corner && mm(o) <= mm(all) && (!o.zoneMiss || !!all.zoneMiss) && pc(o) <= pc(all)
    && (mm(o) < mm(all) || (!o.zoneMiss && !!all.zoneMiss) || pc(o) < pc(all)));
  if (take.some(Boolean)) {
    const shPer = perOf;
    perOf = (vi) => (take[vi] ? { ...own[vi], ...own[vi].per[0] } : shPer(vi));
    console.log(`${rid}: одной пары с видами зоны и чистой обложкой на ${list.length} стилей нет — своя пара у стилей ${list.filter((_, vi) => take[vi]).map((v) => v.style || v.id).join(", ")}`);
  }
  const bad = list.filter((_, vi) => pc(take[vi] ? own[vi] : all)).map((v) => v.style || v.id);
  if (bad.length) console.log(`WARN:demo_cams: ${rid} — обложка не чистая у стилей ${bad.join(", ")}`);
}
// обложка без главной вещи комнаты (T-20261107-01, `camPairAll`: ни в одном виде пары она не видна на 2/3) — громко в лог сборки, по
// стилям, у которых такая пара ВЫШЛА В ДАННЫЕ (T-20261108-73/3: общую пару спальни 2 без главного стили сменили на свои, а WARN
// про отброшенную пару писался до выбора)
if (shared) {
  const pm = list.map((v, vi) => ({ v, p: { ...all, ...(perOf(vi) ?? {}) } })).filter((x) => x.p.posterMiss);
  if (pm.length) console.log(`WARN:demo_cams: ${rid} — обложка без главной вещи комнаты у стилей ${pm.map((x) => x.v.style || x.v.id).join(", ")} (${pm[0].p.how.split(", главное ")[1] ?? ""})`);
}
D.cams_shared = D.cams_shared || shared;
// СТОРОЖ СРЕЗА КРАЕМ ЖИВОГО 3D (T-20261108-73, ведущий 08.11: тумба с ТВ у левого края «От окна» — тёмный кусок ~1/6 ширины телефона).
// Срез входит в ключ пары (`camBigCut` → `camLiveBigCut`), но после двух концов, главного целиком и обязательного: гостиная 08.11 —
// обеденный стол в углу у ТВ виден от окна только взглядом вдоль стены с ТВ. Остался кусок ≥ CUT_WARN кадра — громко, по стилю
const CUT_WARN = 0.1, cutWarn = [];
const bigOf = (it) => api.camIsMain(it) || ((api.camZ().core || {})[api.camRole(it)] || 0) >= 1;
for (const [vi, v] of list.entries()) {
  const pr = shared ? { ...all, ...(perOf(vi) ?? {}) } : api.camPairAll([itsOf(v)], W, H, corners, { prev: prevOf(v) });
  v.cams = pr.cams.map((c) => ({ name: c.name, x: Math.round(c.x), y: Math.round(c.y), rot: Math.round(c.rot || 0), fov: c.fov || 72, pose: 2,
    // подбор парой (demo-12, ADR-0304, по умолчанию с 17.10) несёт сдвиг вертикального кадра телефона
    ...(typeof c.pshift === "number" ? { pshift: c.pshift } : {}), ...(c.crop ? { crop: c.crop } : {}),
    // обложка комнаты на главной (T-32/3, правило зоны `poster`)
    ...(c.poster ? { poster: true } : {}) }));
  v.cam_level = pr.level;
  v.cam_cover = { covered: (pr.covered ?? []).length, missing: (pr.missing ?? []).map((m) => ({ id: m.id, role: m.role, must: m.must, reason: m.reason })) };
  console.log(`${v.id}: ${pr.how ?? ""}${(pr.missing ?? []).length ? ` — не видно: ${pr.missing.map((m) => `${m.role} (${m.reason})`).join(", ")}` : ""}`);
  // ступень ослаблений итоговой пары варианта (v2) — машинной строкой, какой бы веткой выше пара ни пришла (общая, своя, запасная)
  for (const w of pr.warns ?? []) console.log(`WARN:demo_cams room=${rid} style=${v.style || v.id} ${w}`);
  const its = IT[vi], cuts = v.cams.flatMap((c) => api.camLiveBigCut(c, its, W, H, new Set(), bigOf).filter((q) => q.fr >= CUT_WARN)
    .map((q) => `${c.name} ${api.camRole(its[q.i])} ${Math.round(q.fr * 100)} %`));
  if (cuts.length) cutWarn.push(`${v.style || v.id} (${cuts.join(", ")})`);
  n += 1;
}
if (cutWarn.length) console.log(`WARN:demo_cams: ${rid} — крупное срезано краем живого 3D (кусок ≥ ${CUT_WARN * 100} % кадра): ${cutWarn.join("; ")} — пары чище подбор не нашёл`);
}
// подменой, не обрезкой (T-20261105-59): оборвался процесс посреди записи — demo-data.json остаётся вчерашним целиком
const tmp = `${file}.cams-${process.pid}.tmp`;
writeFileSync(tmp, JSON.stringify(D, null, 1));
renameSync(tmp, file);
console.log(`ракурсы окна в данных: вариантов ${n} (${(D.variants ?? []).map((v) => `${v.id} ступень ${v.cam_level}`).join(", ")})`);
