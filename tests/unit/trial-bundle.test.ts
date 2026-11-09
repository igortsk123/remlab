import { promises as fs } from "node:fs";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { bundleProblem, trialBundle } from "@/contracts/trial-bundle";
import { bundleDir, bundleName, pruneBundles, readBundle, removeBundles, writeBundle } from "@/lib/trial/bundle";
import { bundleOf } from "./_trial-bundle-db";

// Данные страницы задания без базы (agent-trial-08, задача А): форма, связи, имена файлов, симлинки. С базой — `_trial-bundle-db.ts`.
const ID = "A".repeat(22);
const DIR = path.join(process.cwd(), ".vitest", `trial-bundle-${process.pid}`);
const SAMPLE_FILE = path.join(process.cwd(), "tests/fixtures/trial-bundle.sample.json");

describe("форма и связи", () => {
  const parse = (over: Record<string, unknown> = {}) => trialBundle.safeParse(bundleOf(ID, over));
  const problem = (over: Record<string, unknown>) => bundleProblem(trialBundle.parse(bundleOf(ID, over)), ID);
  const v = { id: "x", room_id: "living", style: "s", items: [], pending: true, furniture_state: "pending" };
  const room = (furniture_state: string, furniture_text: string | null = null) => ({ id: "living", furniture_state, furniture_text });

  it("годные данные проходит, лишние поля страницы остаются", () => {
    const p = parse({ plan: { a: 1 }, sets: [] });
    expect(p.success && (p.data as Record<string, unknown>).plan).toEqual({ a: 1 });
    expect(bundleProblem(trialBundle.parse(bundleOf(ID)), ID)).toBeNull();
  });

  it("битая форма: нет вариантов, нет правил, кривой id комнаты, нечисловая стена", () => {
    expect(parse({ variants: [] }).success).toBe(false);
    expect(parse({ rules: undefined }).success).toBe(false);
    expect(parse({ variants: [{ ...v, room_id: "../x" }] }).success).toBe(false);
    expect(parse({ room: { w: "4", d: 3, title: "", openings: [], radiators: [] } }).success).toBe(false);
  });

  it("опрос: без `quiz.questions` ссылка покупателя `?quiz=1` не откроет опрос — такие данные не принимаем", () => {
    expect(parse({ quiz: undefined }).success).toBe(false);
    expect(parse({ quiz: { questions: [] } }).success).toBe(false);
    expect(parse({ quiz: { a: 1 } }).success).toBe(false);
  });

  it("связи: чужое задание, повтор варианта, вариант без комнаты, «ждёт мебель» с мебелью", () => {
    expect(bundleProblem(trialBundle.parse(bundleOf("B".repeat(22))), ID)).toBe("wrong_job");
    expect(problem({ variants: [v, v] })).toBe("variant_id_repeated");
    expect(problem({ apartment_rooms: [room("pending"), room("pending")] })).toBe("room_id_repeated");
    expect(problem({ variants: [{ ...v, room_id: "bedroom-1" }] })).toBe("variant_without_room");
    expect(problem({ variants: [{ ...v, items: [{ role: "sofa", x: 1, y: 2 }] }] })).toBe("pending_with_items");
  });

  it("исход мебели по комнате: только четыре значения, отказ — с текстом, «готово» — с мебелью", () => {
    expect(parse({ apartment_rooms: [{ id: "living" }] }).success).toBe(false);
    expect(parse({ apartment_rooms: [room("failed")] }).success).toBe(false);
    expect(problem({ apartment_rooms: [room("refused", "  ")] })).toBe("refused_without_text");
    expect(problem({ apartment_rooms: [room("refused")] })).toBe("refused_without_text");
    expect(problem({ apartment_rooms: [room("refused", "Не поместилось.")] })).toBeNull();
    expect(problem({ apartment_rooms: [room("ready")] })).toBe("ready_without_items");
  });

  it("«не обставляется» (кухня, санузел, прихожая) — с текстом; мебель только у «готово»; завершено — без «подбирается»", () => {
    const full = { ...v, pending: false, furniture_state: "ready", items: [{ role: "диван", x: 1, y: 2 }] };
    expect(problem({ apartment_rooms: [room("not_furnished")] })).toBe("refused_without_text");
    expect(problem({ apartment_rooms: [room("pending"), { id: "kitchen-1", furniture_state: "not_furnished", furniture_text: "Эту комнату не обставляем." }] })).toBeNull();
    expect(problem({ variants: [full], apartment_rooms: [room("refused", "Нет подходящих товаров.")] })).toBe("items_in_unfurnished_room");
    expect(problem({ trial: { job_id: ID, complete: true } })).toBe("complete_with_pending");
    expect(problem({ trial: { job_id: ID, complete: true }, variants: [full], apartment_rooms: [room("ready")] })).toBeNull();
  });

  it("«ждёт проверки размера» (awaiting_check) — с текстом, без мебели, `done` не держит", () => {
    const full = { ...v, pending: false, furniture_state: "ready", items: [{ role: "диван", x: 1, y: 2 }] };
    const wait = room("awaiting_check", "Размер может быть неточным — поправьте и нажмите «Обустроить».");
    expect(problem({ apartment_rooms: [room("awaiting_check")] })).toBe("refused_without_text");
    expect(problem({ trial: { job_id: ID, complete: true }, variants: [{ ...v, pending: false, furniture_state: "awaiting_check" }],
      apartment_rooms: [wait] })).toBeNull();
    expect(problem({ variants: [full], apartment_rooms: [wait] })).toBe("items_in_unfurnished_room");
  });

  it("второй замок: поля магазина у товара или ленты и кириллица в английской подписи — не принимаем", () => {
    const withSku = (sku: Record<string, unknown>) => ({ ...v, pending: false, furniture_state: "ready", items: [{ role: "диван", x: 1, y: 2, sku }] });
    const ready = [{ ...room("ready"), titleEn: "Lounge" }];
    expect(problem({ variants: [withSku({ name: "Диван", name_en: "Sofa", msid: "m" })], apartment_rooms: ready })).toBeNull();
    expect(problem({ variants: [withSku({ name: "Диван", url: "https://x" })], apartment_rooms: ready })).toBe("shop_field");
    expect(problem({ variants: [withSku({ name: "Диван", price: 1 })], apartment_rooms: ready })).toBe("shop_field");
    expect(problem({ feeds: { диван: [{ name: "Диван", img: "//x" }] } })).toBe("shop_field");
    expect(problem({ apartment_rooms: [{ ...room("pending"), titleEn: "Спальня 2" }] })).toBe("cyrillic_in_english_title");
  });

  it("образец от `trial_bundle.py` (тот же файл сверяет тест Python) проходит контракт: пустая, с мебелью, со спальнями и «не обставляется»", async () => {
    const samples = JSON.parse(await fs.readFile(SAMPLE_FILE, "utf8")) as Record<string, { trial: { job_id: string } }>;
    expect(Object.keys(samples).sort()).toEqual(["empty", "furnished", "rooms"]);
    for (const s of Object.values(samples)) {
      const p = trialBundle.safeParse(s);
      expect(p.success ? null : p.error.issues).toBeNull();
      expect(p.success && bundleProblem(p.data, s.trial.job_id)).toBeNull();
    }
  });
});

describe("файлы версий", () => {
  beforeAll(() => fs.mkdir(DIR, { recursive: true }));
  afterAll(() => fs.rm(DIR, { recursive: true, force: true }));

  it("папка — только из id формата токена", () => {
    expect(bundleDir("/data/trial", ID)).toBe(`/data/trial/${ID}`);
    for (const bad of ["../x", "..", "", `${ID}/..`, `${ID}\0`, "A".repeat(21), "A/".repeat(11)]) expect(bundleDir("/data/trial", bad)).toBeNull();
  });

  it("запись целиком: без временных файлов, версия читается; неверный id — отказ", async () => {
    await writeBundle(DIR, ID, 1, '{"a":1}');
    expect(await fs.readdir(path.join(DIR, ID))).toEqual([bundleName(1)]);
    expect(await readBundle(DIR, ID, 1)).toBe('{"a":1}');
    expect(await readBundle(DIR, ID, 2)).toBeNull();
    expect(await readBundle(DIR, ID, 0)).toBeNull();
    await expect(writeBundle(DIR, "../evil", 1, "{}")).rejects.toThrow("bad_job_id");
  });

  it("симлинк вместо папки: запись отказывает, чтение null, удаление убирает ссылку, цель цела", async () => {
    const target = path.join(DIR, "target"), link = "L".repeat(22);
    await fs.mkdir(target);
    await fs.writeFile(path.join(target, bundleName(1)), "secret");
    await fs.symlink(target, path.join(DIR, link));
    expect(await readBundle(DIR, link, 1)).toBeNull();
    await expect(writeBundle(DIR, link, 2, "{}")).rejects.toThrow("bundle_dir_not_a_directory");
    await removeBundles(DIR, link);
    expect(await fs.readdir(target)).toEqual([bundleName(1)]);
    await expect(fs.lstat(path.join(DIR, link))).rejects.toThrow();
  });

  it("чистка: старые версии и забытые временные файлы; свежий временный и текущая — остаются", async () => {
    const id = "C".repeat(22), d = path.join(DIR, id);
    for (const v of [1, 2, 3]) await writeBundle(DIR, id, v, "{}");
    await fs.writeFile(path.join(d, ".bundle-4.old.tmp"), "x");
    await fs.writeFile(path.join(d, ".bundle-5.new.tmp"), "x");
    await fs.writeFile(path.join(d, "other.json"), "x");
    const old = new Date(Date.now() - 2 * 3_600_000);
    await fs.utimes(path.join(d, ".bundle-4.old.tmp"), old, old);
    await pruneBundles(DIR, id, 2);
    expect((await fs.readdir(d)).sort()).toEqual([".bundle-5.new.tmp", "bundle-2.json", "bundle-3.json", "other.json"]);
  });
});
