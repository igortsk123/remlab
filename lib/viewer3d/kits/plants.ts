// РАСТЕНИЯ В КАШПО И ВАЗАХ (T-20261117-07, владелец TG 1307: «растения универсальные красивые … как декор для кашпо и ваз»).
//
// Кашпо и ваза в /demo — модели товаров, пустые. Универсальное растение (CC0, Poly Haven; `data/flat3d/plants.json`) ставится в горло
// носителя: верх и диаметр берутся из меша носителя, масштаб — по горлу. Это НЕ товар: нет цены, строки списка и замены, в состав
// и сумму не входит; сцена рисует его ребёнком группы носителя (двигается, исчезает и сменяется вместе с ним).
//
// Правила — данные (`plants.json`: `hosts` роль → тип, `fit` по типу), в коде нет ни товаров, ни сцен. Нет подходящего растения,
// горла или файла — носитель остаётся как был.

import * as THREE from "three";

import plantsJson from "@/data/flat3d/plants.json";

export type PlantKind = "green" | "dry";

/** Где стоит носитель: на полу (напольное кашпо, большая ваза) или выше пола (на столе, полке, тумбе). `shelf` — готовое мелкое
 * растение в горшке на верх тумбы/комода (своего носителя нет; слот под него — отдельный шаг, T-20261117-21). */
export type PlantMount = "floor" | "table" | "shelf";

export interface PlantDef {
  id: string;
  kind: PlantKind;
  /** Стили, к которым растение подходит; «any» — к любому. */
  styles: string[];
  /** Растение берётся для горла не уже этого размера, см (крупное — в крупное). */
  minThroatCm: number;
  /** … и не шире этого, см (мелкое — в мелкое). Нет — без верхнего предела. */
  maxThroatCm?: number;
  /** Для каких носителей: напольных, настольных. Нет — для любых. */
  mounts?: PlantMount[];
}

interface Fit {
  crownOverThroat: number;
  minHeightCm: number;
  maxHeightCm: number;
  /** Во сколько раз выше носителя (только сухоцветы). */
  heightOverCarrier?: number;
  /** Высота зелени = диаметр горла × это (напольное кашпо: растение «в рост», не рассада), в рамках [min, max]. */
  heightOverThroat?: number;
  /** Насколько основание уходит ниже края горла: постоянная часть, см. */
  sinkCm: number;
  /** … и доля высоты растения. */
  sinkFracOfHeight: number;
}

export interface PlantRules {
  base: string;
  rev: string;
  hosts: Record<string, PlantKind>;
  /** Носитель выше этой отметки от пола, см — настольный, иначе напольный. */
  floorMaxElevCm: number;
  fit: Record<PlantKind, Record<"floor" | "table", Fit>>;
  throat: {
    topSliceFrac: number; minSliceCm: number; minDiameterCm: number;
    /** Разброс высоты верхней кромки по окружности, доля диаметра горла: больше — срез наискосок, растения нет. */
    maxRimSpread: number;
    /** Горло / наибольший диаметр тела: больше — растения нет (1 — проверка выключена: прямая стенка тоже годится). */
    maxNeckRatio: number;
    /** Начала слов названия носителя, при которых растения нет (косой срез, шар, чаша, флорариум …). */
    nameStopWords: string[];
  };
  plants: PlantDef[];
}

export const PLANT_RULES = plantsJson as unknown as PlantRules;

/** Горло носителя в осях его группы, метры: центр отверстия, высота края и диаметр. */
export interface Throat {
  x: number;
  z: number;
  topY: number;
  diameterM: number;
}

/** Посадка растения: общий масштаб и положение основания (метры, оси группы носителя). */
export interface PlantFit {
  scale: number;
  x: number;
  y: number;
  z: number;
}

/**
 * Растения в кадре для нейросети (`viewer.capturePhoto`, «реалистичное фото»): пока НЕТ — кадр прежний (T-20261117-07). Включить —
 * `true`: нейросеть увидит в кашпо и вазах те же растения, что в 3D, и дорисует их согласованно, а не придумает своё.
 */
export const PLANTS_IN_PHOTO = false;

/** Выключатель в адресе страницы: `?plants=0` — без растений в кашпо и вазах (откат без выкладки), иначе по умолчанию вкл. */
export function plantsFromUrl(search: string = (globalThis as { location?: { search?: string } }).location?.search ?? ""): boolean | undefined {
  const m = /[?&]plants=([01])(&|$)/.exec(search);
  return m ? m[1] === "1" : undefined;
}

/** Тип растения для носителя по роли предмета («кашпо», «ваза 2»); не носитель — null. */
export function plantKindOf(role: string | null | undefined, rules: PlantRules = PLANT_RULES): PlantKind | null {
  const base = String(role ?? "").replace(/\s+\d+$/, "").trim().toLowerCase();
  return base ? rules.hosts[base] ?? null : null;
}

/** Напольный или настольный носитель — по высоте его дна над полом, см (`placement.elevCm`). */
export function mountOf(elevCm: number | null | undefined, rules: PlantRules = PLANT_RULES): PlantMount {
  return (elevCm ?? 0) > rules.floorMaxElevCm ? "table" : "floor";
}

/** Адрес лёгкой копии; `?v=` — версия набора (файлы раздаются с долгим кэшем). */
export function plantUrl(id: string, rules: PlantRules = PLANT_RULES): string {
  return `${rules.base}${id}.glb?v=${rules.rev}`;
}

/** Устойчивое число 0…2³²−1 из строки (выбор растения не прыгает между пересборками сцены). */
function hash32(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** Разворот растения вокруг своей оси, градусы: устойчивый от `seed` (модель носителя). Один расчёт для 3D и для экспорта сцены в рендер. */
export function plantYawDeg(seed: string): number {
  return hash32(seed) % 360;
}

/**
 * Какое растение ставить: тип — по носителю, затем те, что подходят по стилю и размеру горла; из них — по устойчивому числу от
 * `seed` (модель носителя): один и тот же носитель всегда с одним растением. Стиль не задан — подходят «any»-растения.
 */
export function pickPlant(kind: PlantKind, mount: PlantMount, throatCm: number, seed: string, style?: string | null,
  rules: PlantRules = PLANT_RULES): PlantDef | null {
  const fits = rules.plants.filter((p) => p.kind === kind && throatCm >= p.minThroatCm && throatCm <= (p.maxThroatCm ?? Infinity)
    && (!p.mounts || p.mounts.includes(mount)) && (p.styles.includes("any") || (!!style && p.styles.includes(style))));
  if (!fits.length) return null;
  return fits[hash32(seed) % fits.length]!;
}

/**
 * Горло носителя по его мешу: верхняя полоса вершин (доля высоты, не тоньше `minSliceCm`) — край отверстия. Центр — середина
 * рамки полосы, диаметр — среднее двух её сторон. Оси — группы носителя (`frame`): поворот места в расчёт не входит.
 * Горло уже `minDiameterCm` или меш без вершин — null (растение не ставим).
 */
export function throatOf(root: THREE.Object3D, frame: THREE.Object3D, rules: PlantRules = PLANT_RULES): Throat | null {
  const m = measureThroat(root, frame, rules);
  return m.throat && !m.why ? m.throat : null;
}

/** Строка журнала растений сцены (`FlatViewer.plantReport`): носитель и итог — `planted` или причина, почему растения нет. */
export interface PlantLogEntry {
  slotId: string;
  title: string;
  role: string;
  mount: PlantMount;
  why: "planted" | "name" | "slanted" | "wide" | "none" | "no-plant";
  word?: string;
  plant?: string;
  rimSpread?: number;
  neckRatio?: number;
  throatCm?: number;
  /** Что сказала геометрия горла (даже если растения нет уже по названию): для сверки двух сигналов. */
  geoWhy?: ThroatMeasure["why"];
}

/** Результат замера горла: само горло (если нашлось) и причина отказа (если растение ставить нельзя), метрики — для разбора. */
export interface ThroatMeasure {
  throat: Throat | null;
  /** `no-mesh` — нет вершин; `narrow` — горло уже `minDiameterCm`; `slanted` — срез наискосок; `wide` — горло не уже тела (отношение выше порога). Нет — годится. */
  why: "no-mesh" | "narrow" | "slanted" | "wide" | null;
  /** Разброс высоты верхней кромки по окружности, доля диаметра горла (0 — кромка горизонтальна). */
  rimSpread: number;
  /** Диаметр горла / наибольший диаметр тела (1 — прямая стенка, меньше — шея). */
  neckRatio: number;
}

/**
 * Замер горла с проверкой: кромка должна быть почти горизонтальной (`maxRimSpread`: разброс высоты края по окружности ≤ доли диаметра
 * горла — косой срез, чаша, «аквариум» не берут букет) и тело не должно быть сильно шире горла (`maxNeckRatio`).
 * Кромка: вершины верхних 45 % высоты по 12 секторам вокруг центра — в каждом самая высокая; разброс — между секторами, где вершины есть.
 */
export function measureThroat(root: THREE.Object3D, frame: THREE.Object3D, rules: PlantRules = PLANT_RULES): ThroatMeasure {
  const res = (throat: Throat | null, why: ThroatMeasure["why"], rimSpread = 0, neckRatio = 0): ThroatMeasure => ({ throat, why, rimSpread, neckRatio });
  frame.updateMatrixWorld(true);
  root.updateMatrixWorld(true);
  const inv = frame.matrixWorld.clone().invert();
  const pts: THREE.Vector3[] = [];
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    const pos = m.isMesh ? (m.geometry.getAttribute("position") as THREE.BufferAttribute | undefined) : undefined;
    if (!pos) return;
    const to = m.matrixWorld.clone().premultiply(inv);
    const step = Math.max(1, Math.floor(pos.count / 30000));
    for (let i = 0; i < pos.count; i += step) pts.push(new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(to));
  });
  if (!pts.length) return res(null, "no-mesh");
  let lo = Infinity, hi = -Infinity;
  for (const p of pts) { if (p.y < lo) lo = p.y; if (p.y > hi) hi = p.y; }
  const slice = Math.max(rules.throat.minSliceCm / 100, (hi - lo) * rules.throat.topSliceFrac);
  const top = new THREE.Box3();
  for (const p of pts) if (p.y >= hi - slice) top.expandByPoint(p);
  const diameterM = ((top.max.x - top.min.x) + (top.max.z - top.min.z)) / 2;
  const throat: Throat = { x: (top.min.x + top.max.x) / 2, z: (top.min.z + top.max.z) / 2, topY: hi, diameterM };
  if (diameterM * 100 < rules.throat.minDiameterCm) return res(null, "narrow");

  // наибольший диаметр тела: средняя сторона рамки по 12 горизонтальным срезам
  const H = Math.max(hi - lo, 1e-6);
  const slabs = Array.from({ length: 12 }, () => new THREE.Box3());
  for (const p of pts) slabs[Math.min(11, Math.floor(((p.y - lo) / H) * 12))]!.expandByPoint(p);
  let body = 0;
  for (const b of slabs) if (!b.isEmpty()) body = Math.max(body, (b.max.x - b.min.x + (b.max.z - b.min.z)) / 2);
  const neckRatio = body > 1e-6 ? Math.min(diameterM / body, 9) : 1;

  // кромка: в верхних 45 % высоты — самая высокая вершина каждого из 12 секторов вокруг центра рамки этой части
  const upper = pts.filter((p) => p.y >= hi - 0.45 * H);
  const ub = new THREE.Box3().setFromPoints(upper);
  const cx = (ub.min.x + ub.max.x) / 2, cz = (ub.min.z + ub.max.z) / 2;
  const SECT = 12;
  const rim = new Array<number>(SECT).fill(-Infinity);
  for (const p of upper) {
    const s = Math.min(SECT - 1, Math.floor(((Math.atan2(p.z - cz, p.x - cx) + Math.PI) / (2 * Math.PI)) * SECT));
    if (p.y > rim[s]!) rim[s] = p.y;
  }
  const have = rim.filter((y) => y > -Infinity);
  const rimSpread = have.length >= 8 ? (Math.max(...have) - Math.min(...have)) / Math.max(diameterM, 1e-6) : 0;
  const why = rimSpread > rules.throat.maxRimSpread ? "slanted" : neckRatio > rules.throat.maxNeckRatio ? "wide" : null;
  return res(throat, why, rimSpread, neckRatio);
}

/**
 * Слово названия носителя, по которому растения нет: первое совпадение со списком `throat.nameStopWords` (шаблоны слов целиком,
 * «Ваза-шар … косой срез» → «шар»; «Шарм» не совпадает); нет — null.
 */
export function blockedByName(title: string | null | undefined, rules: PlantRules = PLANT_RULES): string | null {
  const t = String(title ?? "").toLowerCase();
  for (const w of rules.throat.nameStopWords) {
    const m = new RegExp(`(?:^|[^а-яёa-z0-9])(${w})(?![а-яёa-z0-9])`, "iu").exec(t);
    if (m) return m[1]!;
  }
  return null;
}

/**
 * Масштаб и положение растения. Размер растения `plantM` (метры: ширина кроны, высота, глубина) — из самой модели.
 *  • зелень (кашпо): крона = горло × `crownOverThroat`, высота зажата в [min, max];
 *  • сухоцветы (ваза): высота = носитель × `heightOverCarrier` в [min, max], крона не шире горла × `crownOverThroat`.
 * Основание модели — в нуле на оси; ставим его на край горла, углубив на `sinkCm` + долю высоты (стебли уходят в вазу).
 */
export function fitPlant(kind: PlantKind, mount: PlantMount, plantM: { w: number; h: number; d: number }, throat: Throat,
  carrierHeightM: number, rules: PlantRules = PLANT_RULES): PlantFit {
  const f = rules.fit[kind][mount === "floor" ? "floor" : "table"];   // `shelf` (готовое растение) носителя не подгоняет — сюда не попадает
  const crown = Math.max(plantM.w, plantM.d, 1e-4);
  const h = Math.max(plantM.h, 1e-4);
  const lo = f.minHeightCm / 100, hi = f.maxHeightCm / 100;
  let s: number;
  if (kind === "dry") {
    const want = Math.min(hi, Math.max(lo, carrierHeightM * (f.heightOverCarrier ?? 2)));
    s = Math.min(want / h, (throat.diameterM * f.crownOverThroat) / crown);
  } else if (f.heightOverThroat) {
    const want = Math.min(hi, Math.max(lo, throat.diameterM * f.heightOverThroat));
    s = Math.min(want / h, (throat.diameterM * f.crownOverThroat) / crown);
  } else {
    s = (throat.diameterM * f.crownOverThroat) / crown;
    s = Math.min(hi / h, Math.max(lo / h, s));
  }
  const sink = f.sinkCm / 100 + f.sinkFracOfHeight * h * s;
  return { scale: s, x: throat.x, y: throat.topY - sink, z: throat.z };
}

/** Размер растения по его модели (метры). */
export function plantSize(source: THREE.Object3D): { w: number; h: number; d: number } {
  const size = new THREE.Box3().setFromObject(source).getSize(new THREE.Vector3());
  return { w: size.x, h: size.y, d: size.z };
}

/**
 * Растение к посадке: копия модели с общим масштабом и разворотом (устойчивым от `seed`, чтобы одинаковые носители не стояли
 * «клонами»). Помечено `userData.plant` — не товар: выбор и ценник у носителя.
 */
export function placePlant(source: THREE.Object3D, fit: PlantFit, seed: string): THREE.Group {
  const g = new THREE.Group();
  const obj = source.clone(true);
  g.add(obj);
  g.scale.setScalar(fit.scale);
  g.rotation.y = (plantYawDeg(seed) * Math.PI) / 180;
  g.position.set(fit.x, fit.y, fit.z);
  g.userData.plant = true;
  g.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh) return;
    m.castShadow = true;
    m.receiveShadow = true;
  });
  return g;
}
