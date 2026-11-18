import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// СТРОГО ФОТО НЕЙРОСЕТИ (T-20261107-35/1 часть 0; владелец TG 341, TG 378; план photo-before-publish-01 § А). Чистая функция — блок
// REALSHOT страницы демо (`realPubPick`, обёртка `realisticPublishedShot`); тест читает блок из страницы, как QUIZPICK.
const SRC = "tools/scout/flat215-demo/index.html";
type Shot = { url?: string; quality?: string; stateId?: string; vid?: string; camera?: string; ts?: number; bad?: boolean };

const src = readFileSync(SRC, "utf8");
const block = src.slice(src.indexOf("// REALSHOT START"), src.indexOf("// REALSHOT END"));
const realPubPick = new Function(`${block};return realPubPick;`)() as (
  list: Shot[], st: string, vid: string, cam: string, camOk: (x: Shot) => boolean, noOld?: boolean,
) => Shot | null;
const camOk = (x: Shot) => !x.bad;   // в странице — `shotCamOk(x, v.cams)`: точка кадра совпадает с нынешней
const pick = (list: Shot[], cam = "C1") => realPubPick(list, "S-now", "set1", cam, camOk)?.url ?? null;
const sh = (url: string, o: Partial<Shot>): Shot => ({ url, quality: "realistic", vid: "set1", camera: "C1", ts: 1, ...o });

describe("realisticPublishedShot — порядок и запреты", () => {
  it("1) фото нейросети этой расстановки; точка cam важнее, нет её — другая точка того же состояния", () => {
    const list = [sh("old", { stateId: "S-old", ts: 9 }), sh("now-c2", { stateId: "S-now", camera: "C2" }), sh("now-c1", { stateId: "S-now" })];
    expect(pick(list)).toBe("now-c1");
    expect(pick([sh("now-c2", { stateId: "S-now", camera: "C2" })])).toBe("now-c2");
  });
  it("2) этой нет — последнее (по времени) фото того же варианта и той же точки из прежних расстановок", () => {
    const list = [sh("old-1", { stateId: "S-a", ts: 5 }), sh("old-2", { stateId: "S-b", ts: 7 }), sh("old-c2", { stateId: "S-c", camera: "C2", ts: 9 }),
      sh("other-v", { stateId: "S-d", vid: "set6", ts: 10 })];
    expect(pick(list)).toBe("old-2");
    expect(pick(list, "C2")).toBe("old-c2");
  });
  it("3) нет ни того, ни другого — null (вариант не показываем)", () => {
    expect(pick([])).toBeNull();
    expect(pick([sh("other-v", { stateId: "S-x", vid: "set6" })])).toBeNull();
  });
  it("черновик (3D) — никогда, даже этой расстановки и единственный", () => {
    expect(pick([sh("draft-now", { stateId: "S-now", quality: "draft" })])).toBeNull();
    expect(pick([sh("draft-now", { stateId: "S-now", quality: "draft", ts: 9 }), sh("old", { stateId: "S-old" })])).toBe("old");
    expect(pick([sh("live", { stateId: "S-now", quality: "live" })])).toBeNull();
  });
  it("точка этой расстановки не совпадает с нынешней — на шаге 1 кадр не годится, на шаге 2 годится (прежнее — это картинка)", () => {
    // сборка 15:19 сдвинула точку 1: у гостиных C1 не совпадает, C2 совпадает — раньше шаг 2 требовал и ту же точку, и совпадение → null
    // кадр этой расстановки с несовпадающей точкой на шаге 1 не берётся, но это фото того же варианта — на шаге 2 годится; совпадающее
    // фото прежней расстановки той же точки его опережает
    expect(pick([sh("now-bad", { stateId: "S-now", bad: true })])).toBe("now-bad");
    // T-20261118-20/10: фото ТОГО ЖЕ состава с другой точки главнее фото прежнего состава с нужной (раньше выигрывало более свежее прежнее)
    expect(pick([sh("now-bad", { stateId: "S-now", bad: true, ts: 9 }), sh("old-ok", { stateId: "S-old", ts: 2 })])).toBe("now-bad");
    expect(pick([sh("now-bad", { stateId: "S-now", bad: true, ts: 2 }), sh("old-bad", { stateId: "S-old", bad: true, ts: 5 })])).toBe("now-bad");
    expect(pick([sh("old-c1-bad", { stateId: "S-a", ts: 9, bad: true }), sh("old-c2", { stateId: "S-a", camera: "C2", ts: 5 })])).toBe("old-c1-bad");
  });
  it("шаг 2 — порядок: та же точка и совпадает → та же точка → любая совпадающая → любая; внутри — свежее", () => {
    const a = sh("c1-ok", { stateId: "S-a", ts: 1 }), b = sh("c1-bad", { stateId: "S-b", ts: 8, bad: true });
    const c = sh("c2-ok", { stateId: "S-c", camera: "C2", ts: 9 }), d = sh("c3-bad", { stateId: "S-d", camera: "C3", ts: 10, bad: true });
    expect(pick([a, b, c, d])).toBe("c1-ok");
    expect(pick([b, c, d])).toBe("c1-bad");
    expect(pick([c, d])).toBe("c2-ok");
    expect(pick([d])).toBe("c3-bad");
    expect(pick([sh("c1-new", { stateId: "S-a", ts: 7, bad: true }), sh("c1-old", { stateId: "S-b", ts: 3, bad: true })])).toBe("c1-new");
  });
  it("шаг 2 — только тот же вариант и только фото нейросети", () => {
    expect(pick([sh("other-v", { stateId: "S-x", vid: "set6", camera: "C2" })])).toBeNull();
    expect(pick([sh("draft-old", { stateId: "S-x", quality: "draft", camera: "C2" })])).toBeNull();
  });
  it("кадр без адреса или без номера состояния на шаге 1 не считается кадром этой расстановки", () => {
    expect(pick([sh("", { stateId: "S-now" })])).toBeNull();
    expect(pick([sh("nostate", { stateId: "" , vid: "set6" })])).toBeNull();
  });
});

// ФОТО ВИДА В ОКНЕ — ТОЛЬКО СО СВОЕЙ ТОЧКИ (T-20261108-73, ведущий 08.11: «подпись не должна врать» — после пересборки видов «Со стороны
// окна» стояло над фото, снятым от двери). `vwPubShotAt`: годен кадр с именем точки `C<k+1>` и той же точкой (`shotCamOk`); иначе null —
// у вида фото нет, как у любого вида без фото. Карточке главной прежнее фото другой точки по-прежнему годно (шаг 2 выше, TG 378)
describe("vwPubShotAt — фото вида в окне только со своей точки", () => {
  const cut = (a: string, b: string) => src.slice(src.indexOf(a), src.indexOf(b));
  const at = src.indexOf("function vwPubShotAt("), fnSrc = src.slice(at, src.indexOf("\n}", at) + 2);
  const vwPubShotAt = new Function(`${src.slice(src.indexOf("const camAng="), src.indexOf("\n", src.indexOf("const camAng=")))};
${cut("// SHOTCAM START", "// SHOTCAM END")};${block};${fnSrc};return vwPubShotAt;`)() as (
    list: Shot[], st: string, vid: string, cs: { name: string; x: number; y: number; rot: number; fov: number }[], k: number) => Shot | null;
  const door = { x: 436, y: 232, rot: -82, fov: 84 }, win = { x: 60, y: 205, rot: 50, fov: 90 }, oldC2 = { x: 409, y: 205, rot: -100, fov: 78 };
  const now = [{ name: "C1", ...door }, { name: "C2", ...win }];
  const shot = (url: string, camera: string, c2: typeof win, o: Partial<Shot> = {}) =>
    ({ ...sh(url, { stateId: "S-now", camera, ...o }), cams: [{ name: "C1", ...door }, { name: "C2", ...c2 }] }) as Shot;
  it("кадр C2 снят с прежней точки (у двери) — у вида «От окна» фото нет; та же точка — есть", () => {
    // T-20261118-20/10: кадр ТОГО ЖЕ состава с прежней точки — не «нет фото», а то, что человек купит (ключ главнее ракурса)
    expect(vwPubShotAt([shot("c2-old", "C2", oldC2)], "S-now", "set1", now, 1)?.url).toBe("c2-old");
    expect(vwPubShotAt([shot("c2-now", "C2", win)], "S-now", "set1", now, 1)?.url).toBe("c2-now");
    // точка C1 у этих кадров та же — C1 годен, хотя у C2 в той же сборке точка сменилась
    expect(vwPubShotAt([shot("c1", "C1", oldC2)], "S-now", "set1", now, 0)?.url).toBe("c1");
  });
  it("чужая точка вместо своей не подставляется: у C2 нет своего кадра — C1 не берём; прежней расстановки той же точки — берём", () => {
    expect(vwPubShotAt([shot("c1", "C1", win)], "S-now", "set1", now, 1)).toBeNull();
    expect(vwPubShotAt([shot("c2-prev", "C2", win, { stateId: "S-old" })], "S-now", "set1", now, 1)?.url).toBe("c2-prev");
    expect(vwPubShotAt([shot("c2-prev-old", "C2", oldC2, { stateId: "S-old" })], "S-now", "set1", now, 1)).toBeNull();
  });
  // ПЕРЕСЪЁМКА (T-20261108-73/3, владелец TG 666): ночь (`tools/ops/demo-realistic.mjs`) снимает пару, если хоть у одного вида нет фото
  // своей точки (`vwRealMissing`). Прежде — только если фото нет ни у одного: C1 на месте, C2 сдвинут — пару не снимали никогда
  const fm = src.indexOf("function vwRealMissing("), vwRealMissing = new Function(`${src.slice(src.indexOf("const camAng="), src.indexOf("\n", src.indexOf("const camAng=")))};
${cut("// SHOTCAM START", "// SHOTCAM END")};${src.slice(fm, src.indexOf("\n}", fm) + 2)};return vwRealMissing;`)() as
    (have: Shot[], cs: { name?: string }[]) => string[];
  const have = (list: Shot[]) => now.map((_, k) => vwPubShotAt(list, "S-now", "set1", now, k)).filter((x): x is Shot => !!x);
  it("пересъёмка: C1 своей точки, C2 снят с прежней — нужно фото вида C2 (пара в очереди), хотя одно фото у пары есть", () => {
    const part = have([shot("c1", "C1", oldC2), shot("c2-old", "C2", oldC2)]);
    expect(part.map((x) => x.url)).toEqual(["c1", "c2-old"]);   // фото C2 того же состава с прежней точки показывается, но своей точки не закрывает
    expect(vwRealMissing(part, now)).toEqual(["C2"]);
    expect(vwRealMissing(have([shot("c1", "C1", win), shot("c2", "C2", win)]), now)).toEqual([]);
    expect(vwRealMissing([], now)).toEqual(["C1", "C2"]);
    expect(vwRealMissing([], [{}, {}])).toEqual(["C1", "C2"]);
  });
  it("ночной отбор пересъёмки — по `vwRealMissing`, не «нет ни одного фото»", () => {
    const night = readFileSync("tools/ops/demo-realistic.mjs", "utf8");
    expect(night).toMatch(/vwRealMissing\(vwRealShots\(\), cams \|\| loadCams\(\)\)/);
    expect(night).toMatch(/const want = force \? [^\n]*: miss\.length > 0;/);
    expect(night).not.toMatch(/: !vwRealShots\(\)\.length;/);
  });
});

describe("страница: главная, вкладки и опрос берут только строгую функцию", () => {
  const fn = (name: string) => { const at = src.indexOf(`function ${name}(`); return src.slice(at, src.indexOf("\nfunction ", at + 10)); };
  it("homeModel (карточки и вкладки) и photoOf (опрос) — realisticPublishedShot, не pubShot", () => {
    expect(fn("homeModel")).toContain("realisticPublishedShot(");
    expect(fn("homeModel")).not.toContain("pubShot(");
    const quiz = src.slice(src.indexOf("function photoOf("), src.indexOf("function photoOf(") + 200);
    expect(quiz).toContain("realisticPublishedShot(");
    expect(quiz).not.toContain("pubShot(");
  });
  it("карточка главной: ни черновика pubShot, ни кадра 3D liveShot", () => {
    const draw = fn("drawHome");
    expect(draw).toContain("realisticPublishedShot(");
    expect(draw).not.toMatch(/pubShot\(|liveShot\(/);
  });
});

// ЕДИНЫЙ ВЫБОР ФОТО ПО КЛЮЧУ СОСТАВА (T-20261118-20/10; владелец TG 1851: «покупатель видит не то, что купит»). Ключ состава главнее ракурса:
// фото (нейросеть, затем кадр Cycles) этого состава со своей точки → того же состава с другой точки → фото ЧУЖОГО состава только если
// настройка `rules/demo-photo-pick.json` разрешает (окно: `hide` — не показываем, `dim` — затемнённым; главная: `keep` — как было, `hide`)
describe("realPubPick — ключ состава главнее точки; чужой состав — по настройке", () => {
  const pickN = (list: Shot[], noOld: boolean, cam = "C1") => realPubPick(list, "S-now", "set1", cam, camOk, noOld)?.url ?? null;
  it("того же состава с другой точки лучше прежнего состава с нужной точкой", () => {
    const list = [sh("old-ok", { stateId: "S-old", ts: 9 }), sh("now-bad", { stateId: "S-now", bad: true, ts: 1 })];
    expect(pickN(list, false)).toBe("now-bad");
    expect(pickN(list, true)).toBe("now-bad");
  });
  it("кадр Cycles (render) годится наравне с фото нейросети того же состава, нейросеть — первой; render прежнего состава — никогда", () => {
    expect(pickN([sh("cy", { stateId: "S-now", quality: "render" })], true)).toBe("cy");
    expect(pickN([sh("cy", { stateId: "S-now", quality: "render", ts: 9 }), sh("nn", { stateId: "S-now", ts: 1 })], true)).toBe("nn");
    expect(pickN([sh("cy-old", { stateId: "S-old", quality: "render" })], false)).toBeNull();
  });
  it("noOld: фото только чужого состава — null (окно скрывает «Фото»); без noOld — прежнее, как было", () => {
    const list = [sh("old", { stateId: "S-old" })];
    expect(pickN(list, true)).toBeNull();
    expect(pickN(list, false)).toBe("old");
    expect(pickN([sh("draft", { stateId: "S-now", quality: "draft" })], true)).toBeNull();
  });
});

describe("photoRule — выбор А/Б одной настройкой в правилах", () => {
  const at = src.indexOf("function photoRule("), fnSrc = src.slice(at, src.indexOf("\n}", at) + 2);
  const photoRule = new Function("D", `${fnSrc};return photoRule;`) as (D: unknown) => (w: string) => string;
  it("по умолчанию: окно hide (А), главная keep; dim и hide — из rules.photo_pick; неизвестное — по умолчанию", () => {
    expect(photoRule(null)("window")).toBe("hide");
    expect(photoRule({ rules: {} })("home")).toBe("keep");
    expect(photoRule({ rules: { photo_pick: { window_old_key_photo: "dim", home_old_key_photo: "hide" } } })("window")).toBe("dim");
    expect(photoRule({ rules: { photo_pick: { window_old_key_photo: "dim", home_old_key_photo: "hide" } } })("home")).toBe("hide");
    expect(photoRule({ rules: { photo_pick: { window_old_key_photo: "x", home_old_key_photo: "y" } } })("window")).toBe("hide");
  });
  it("файл правил: значения из набора и оба ключа на месте; страница и сборка читают его", () => {
    const r = JSON.parse(readFileSync("tools/scout/rules/demo-photo-pick.json", "utf8"));
    expect(["hide", "dim"]).toContain(r.window_old_key_photo);
    expect(["keep", "hide"]).toContain(r.home_old_key_photo);
    expect(readFileSync("tools/scout/flat215_demo.py", "utf8")).toContain("'photo_pick': _photo_pick()");
  });
  it("страница: окно не считает фото чужого состава фото комнаты; карточка главной — по настройке; Б — своя подпись RU/EN", () => {
    const real = src.slice(src.indexOf("function vwRealShots("), src.indexOf("\n}", src.indexOf("function vwRealShots(")));
    expect(real).toContain("vwPubShotAt(L, st, v.id, cams, k, true)");
    expect(src).toContain("photoRule('home')==='hide'");
    const stale = src.slice(src.indexOf("function vwStalePick("), src.indexOf("\nfunction vwPhotoShots"));
    expect(stale).toContain("untouched&&photoRule('window')==='hide'");
    expect(src).toContain("Мебель в комнате обновилась — это фото прежнего набора");
    expect(src).toContain("The furniture in this room was updated — this is a photo of the previous set");
  });
});

// 16 ВАРИАНТОВ ЖИВЫХ ДАННЫХ (снимок реестра и витрины 18.11, прод a63595a9): выбранное окном фото — только текущего состава, иначе фото нет
describe("16 вариантов живой витрины 18.11 — фото в окне только текущего состава", () => {
  type Cam = { name: string; x: number; y: number; rot: number; fov: number; pose: number };
  const fx = JSON.parse(readFileSync("tests/fixtures/photo-pick-live-1118.json", "utf8")) as {
    poseVer: number; variants: { id: string; style: string; room: string; st: string; cams: Cam[] }[];
    shots: (Shot & { url: string; cams: Cam[] })[];
  };
  const cut = (a: string, b: string) => src.slice(src.indexOf(a), src.indexOf(b));
  const at = src.indexOf("function vwPubShotAt("), fnSrc = src.slice(at, src.indexOf("\n}", at) + 2);
  const make = (poseVer: number) => new Function("POSE_VER", `${src.slice(src.indexOf("const camAng="), src.indexOf("\n", src.indexOf("const camAng=")))};
${cut("// SHOTCAM START", "// SHOTCAM END")};${block};${fnSrc};return vwPubShotAt;`)(poseVer) as
    (list: unknown[], st: string, vid: string, cs: Cam[], k: number, noOld?: boolean) => (Shot & { url: string }) | null;
  const vwPubShotAt = make(fx.poseVer);
  const list = fx.shots;
  it("снимок целый: 16 вариантов, реестр непустой", () => {
    expect(fx.variants).toHaveLength(16);
    expect(list.length).toBeGreaterThan(100);
  });
  it("окно (hide): у каждого вида фото — либо текущего состава, либо нет; чужое состава ни у одной комнаты", () => {
    const bad: string[] = [];
    for (const v of fx.variants) for (const k of v.cams.keys()) {
      const x = vwPubShotAt(list, v.st, v.id, v.cams, k, true);
      if (x && x.stateId !== v.st) bad.push(`${v.id}/C${k + 1}: ${x.stateId}`);
    }
    expect(bad).toEqual([]);
  });
  it("до правки (как было): минимум 10 из 16 комнат показывали фото ЧУЖОГО состава — тест различает старое и новое", () => {
    const olds = fx.variants.filter((v) => v.cams.some((_, k) => { const x = vwPubShotAt(list, v.st, v.id, v.cams, k, false); return x && x.stateId !== v.st; }));
    expect(olds.length).toBeGreaterThanOrEqual(10);
  });
  it("set1 (сканди гостиная): вместо фото старого дивана — фото ТЕКУЩЕГО состава с прежней точки; у кого фото текущего состава нет — null", () => {
    const v = fx.variants.find((x) => x.id === "set1")!;
    const x = vwPubShotAt(list, v.st, v.id, v.cams, 0, true);
    expect(x?.stateId).toBe(v.st);
    expect(x?.quality).toBe("realistic");
    const none = fx.variants.filter((w) => w.cams.every((_, k) => vwPubShotAt(list, w.st, w.id, w.cams, k, true) === null)).map((w) => w.id);
    expect(none).toContain("set4");
    expect(none).toContain("bedroom-2-modern");
  });
  it("главная (keep): ни у одной комнаты фото не пропало — карточка не станет пустой", () => {
    for (const v of fx.variants) {
      const x = realPubPick(list as Shot[], v.st, v.id, "C1", () => true, false);
      expect(x, v.id).not.toBeNull();
    }
  });
});

// ГОТОВЫЙ КАДР ЗАГОТОВКИ В «ФОТО» БЕЗ ЗАКАЗА (T-20261118-20/12): окно нетронутого варианта спрашивает у сервиса `check` (ключ точный, ничего не ставится) и берёт кадры
// как после «Сделать фото» — качество `render`, номер состояния и точки окна. Нет в кэше — как было: фото нет → 3D и кнопка
describe("peekShotRecs — кадры заготовки из ответа check", () => {
  const a = src.indexOf("// PEEKSHOT START"), b = src.indexOf("// PEEKSHOT END");
  const peekShotRecs = new Function(`${src.slice(a, b)};return peekShotRecs;`)() as (j: unknown, o: unknown) => (Shot & { url: string; fid: string; renderKey: string; cached: boolean })[];
  const frames = ["C1", "C2"].map((c, i) => ({ camera: c, url: `/api/render/cycles/frame/${"a".repeat(32)}/${c}.jpg`, id: String(i).repeat(64) }));
  const ok = { cached: true, key: "a".repeat(32), scene_hash: "h", frames };
  const o = { vid: "set1", stateId: "S-now", cams: [{ name: "C1" }], products: [], ts: 5 };
  it("готово → две записи рендера: состояние, точки, ключ и sha256 для «Улучшить»", () => {
    const r = peekShotRecs(ok, o);
    expect(r).toHaveLength(2);
    expect(r.map((x) => [x.camera, x.quality, x.stateId, x.vid, x.cached])).toEqual([["C1", "render", "S-now", "set1", true], ["C2", "render", "S-now", "set1", true]]);
    expect(r[0]?.renderKey).toBe("a".repeat(32));
    expect(r[1]?.fid).toHaveLength(64);
  });
  it("не готово, один кадр, чужие имена, нет состояния — пусто (окно остаётся 3D с кнопкой)", () => {
    expect(peekShotRecs({ ...ok, cached: false }, o)).toEqual([]);
    expect(peekShotRecs({ ...ok, frames: [frames[0]] }, o)).toEqual([]);
    expect(peekShotRecs({ ...ok, frames: [{ ...frames[0], camera: "C3" }, frames[1]] }, o)).toEqual([]);
    expect(peekShotRecs(ok, { ...o, stateId: "" })).toEqual([]);
    expect(peekShotRecs(null, o)).toEqual([]);
    expect(peekShotRecs({ cached: true }, o)).toEqual([]);
  });
  it("страница: спрашивает только нетронутый вариант без фото, после прихода реестра; тур — через ручку тура и только комната с доверием к размерам; вызов при открытии окна и по приходу реестра", () => {
    const fn = src.slice(src.indexOf("async function vwPeekCached("), src.indexOf("// «Улучшить фото»: рендер ЭТОЙ расстановки"));
    expect(fn).toContain("if(TRIAL()&&!trPhotoHere())return;");
    expect(fn).not.toContain("if(TRIAL()||");
    expect(fn).toContain("'/api/trial/'+trJobId()+'/photo'+(trKey()?'?k='+trKey():'')");
    expect(fn).toContain("'/api/render/cycles'");
    expect(fn).toContain("!SHOTS_LOADED");
    expect(fn).toContain("v.mine||v.cid");
    expect(fn).toContain("if(vwRealShots().length)return;");     // и правленая расстановка (T-20261118-20/14/1): check бесплатный, заказа не ставит
    expect(fn).not.toContain("st!==pubStateOf(v)");
    expect(fn).toContain("check:true");
    expect(fn).toContain("curVid()!==vid||curStateId()!==st");
    expect(src).toContain("setTimeout(vwPeekCached,0)");
    expect(src).toContain("vwModeUi(); vwPeekCached();");
  });

  // ЧЕСТНАЯ СТРОКА ПРО МАШИНУ (T-20261118-20/13/2): кадра нет — сервер в `check` отдаёт состояние машины; прогревается / запасной путь — текст сервера (RU/EN) под «Сделать фото», готова — строки нет
  const peekMachineNote = new Function("LANG", `${src.slice(src.indexOf("function peekMachineNote("), src.indexOf("async function vwPeekCached("))};return peekMachineNote;`) as (l: string) => (m: unknown) => string;
  it("peekMachineNote: warming/fallback — текст сервера на языке страницы; ready, пусто, чужое — ''", () => {
    const m = { state: "fallback", text: "Снимок будет готов через ≈2 мин. Подождите, пожалуйста.", text_en: "Your photo will be ready in about 2 min. Please wait.", eta_s: 0 };
    expect(peekMachineNote("ru")(m)).toBe(m.text);
    expect(peekMachineNote("en")(m)).toBe(m.text_en);
    expect(peekMachineNote("ru")({ state: "warming", text: "Первое создание снимка займёт ≈3 мин, далее ≈25 сек. Подождите, пожалуйста.", text_en: "x" })).toBe("Первое создание снимка займёт ≈3 мин, далее ≈25 сек. Подождите, пожалуйста.");
    expect(peekMachineNote("ru")({ state: "ready", text: "", text_en: "" })).toBe("");
    expect(peekMachineNote("ru")(null)).toBe("");
    expect(peekMachineNote("ru")({ state: "fallback", text: 5 })).toBe("");
  });
  it("строка у кнопки: только 3D-окно, кнопка «Сделать фото», без задания и ошибки; кадр взят — строка уходит", () => {
    const ui = src.slice(src.indexOf("// ЧЕСТНАЯ СТРОКА (T-20261118-20/13/2)"), src.indexOf("// ОШИБКА ФОТО (владелец 17.11"));
    expect(ui).toContain("!VJ.job&&!VJ.err&&kind==='make'&&m==='walk'");
    expect(ui).toContain("PEEKM[curVid()+'|'+curStateId()]");
    expect(src).toContain("PEEK[k]=Infinity; delete PEEKM[k];");
  });

  // 16 вариантов живой витрины: кэш заготовки есть у части — у них «Фото» = кадры рендера текущего состояния, у остальных фото нет (3D)
  type Cam = { name: string; x: number; y: number; rot: number; fov: number; pose: number };
  const fx = JSON.parse(readFileSync("tests/fixtures/photo-pick-live-1118.json", "utf8")) as {
    poseVer: number; variants: { id: string; st: string; cams: Cam[] }[]; shots: (Shot & { url: string; cams: Cam[] })[];
  };
  const cut = (x: string, y: string) => src.slice(src.indexOf(x), src.indexOf(y));
  const at = src.indexOf("function vwPubShotAt("), fnSrc = src.slice(at, src.indexOf("\n}", at) + 2);
  const vwPubShotAt = new Function("POSE_VER", `${src.slice(src.indexOf("const camAng="), src.indexOf("\n", src.indexOf("const camAng=")))};
${cut("// SHOTCAM START", "// SHOTCAM END")};${block};${fnSrc};return vwPubShotAt;`)(fx.poseVer) as
    (list: unknown[], st: string, vid: string, cs: Cam[], k: number, noOld?: boolean) => (Shot & { url: string; quality: string; renderKey?: string }) | null;
  it("16 вариантов: у кого кэш заготовки есть — «Фото» = кадры рендера текущего состояния своих точек; у кого нет — фото нет (3D)", () => {
    const cached = new Set(["set4", "set7", "set13", "bedroom-2-modern", "bedroom-1-minimal"]);       // как будто заготовка досчитала эти пять
    const list: unknown[] = [...fx.shots];
    for (const v of fx.variants.filter((x) => cached.has(x.id))) {
      const recs = peekShotRecs({ cached: true, key: v.id.padEnd(32, "0"), frames }, { vid: v.id, stateId: v.st, cams: v.cams, products: [], ts: 9 });
      expect(recs).toHaveLength(2);
      list.push(...recs);
    }
    const got = (v: { id: string; st: string; cams: Cam[] }) => v.cams.map((_, k) => vwPubShotAt(list, v.st, v.id, v.cams, k, true));
    for (const v of fx.variants) {
      const r = got(v);
      if (cached.has(v.id)) {
        expect(r.every((x) => x && x.quality === "render" && x.stateId === v.st), v.id).toBe(true);
      } else {
        // нет кэша: либо фото текущего состояния из реестра (set1, set10…), либо нет вовсе — но не рендер и не чужое состояние
        expect(r.every((x) => !x || (x.stateId === v.st && x.quality !== "render")), v.id).toBe(true);
      }
    }
    const none = fx.variants.filter((v) => !cached.has(v.id) && got(v).every((x) => x === null)).map((v) => v.id);
    expect(none).toContain("set16");
  });
});
