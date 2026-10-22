"use client";

// Нижняя панель выбора — как в режиме строительства Sims (владелец 29.09, со скриншотом игры):
// слева меню (комнаты и что меняем), справа плитки вариантов в два ряда с прокруткой,
// закрыть — крестиком или кликом по свободному месту сцены.
//
// Почему так, а не колонкой справа и не карточкой у предмета: сцена должна занимать весь экран,
// а выбор — лежать одной полосой снизу и не прыгать за предметом.

import { useEffect, useRef, useState } from "react";

import type { Apartment, Slot } from "@/contracts/apartment";
import type { Catalogue, Option } from "@/contracts/configurator";
import { optionsForSlot } from "@/lib/configurator/resolve";
import type { Material } from "@/contracts/configurator";
import { categoryTitle, formatMoney, type Lang } from "@/lib/configurator/i18n";

interface BuildBarProps {
  apartment: Apartment;
  catalogue: Catalogue;
  roomId: string;
  slotId: string | null;
  selections: Record<string, string>;
  lang: Lang;
  onRoom: (roomId: string) => void;
  onSlot: (slotId: string) => void;
  onChoose: (slotId: string, optionId: string) => void;
  /** Взять предмет и передвинуть его по комнате (только в 3D). */
  onMove?: (slotId: string) => void;
  /** Вернуть предмет на место застройщика — показываем, только если его двигали. */
  onResetPlacement?: () => void;
  onClose: () => void;
}

/** Уже этой ширины полоса раскладывается в столбец (телефон в портрете). */
const NARROW_PX = 560;

/** Картинка плитки: у мебели — фото товара, у покрытия — превью материала. */
function tileImage(c: Catalogue, o: Option): string | undefined {
  if (o.previewUrl) return o.previewUrl;
  if (o.asset.kind === "material") {
    const id = o.asset.materialId;
    return c.materials.find((m) => m.id === id)?.previewUrl;
  }
  if (o.asset.kind === "kit") {
    const id = o.asset.materials.door ?? o.asset.materials.body;
    return id ? c.materials.find((m) => m.id === id)?.previewUrl : undefined;
  }
  return undefined;
}

/** Цвет плашки, когда картинки нет. */
function tileColour(c: Catalogue, o: Option): string | undefined {
  const byId = (id?: string): Material | undefined => (id ? c.materials.find((m) => m.id === id) : undefined);
  if (o.asset.kind === "material") return byId(o.asset.materialId)?.colorHex;
  if (o.asset.kind === "kit") return byId(o.asset.materials.door ?? o.asset.materials.body)?.colorHex;
  return undefined;
}

/**
 * Размер плитки — от ЧИСЛА вариантов И от ширины полосы (владелец 30.09: «когда вариантов много,
 * тогда маленькие, когда мало — покрупнее»). Только от числа считать нельзя: четыре «крупные»
 * плитки не влезают в 320 px на телефоне.
 */
function tileLayout(count: number, width: number, narrow: boolean): { size: number; rows: 1 | 2 } {
  if (count === 0) return { size: 96, rows: 1 };
  // узкая полоса (телефон): один ряд на всю ширину с прокруткой вбок
  if (narrow) return { size: Math.max(96, Math.min(140, Math.floor((width - (count - 1) * 6 - 4) / count))), rows: 1 };
  const rows: 1 | 2 = count <= 5 ? 1 : 2;
  const perRow = Math.ceil(count / rows);
  const gaps = (perRow - 1) * 6 + 4;
  const fit = Math.floor((Math.max(220, width) - gaps) / perRow);
  const max = rows === 1 ? 190 : 150;
  return { size: Math.max(88, Math.min(max, fit)), rows };
}

export function BuildBar(props: BuildBarProps) {
  const { apartment, catalogue, roomId, slotId, selections, lang, onRoom, onSlot, onChoose, onClose } = props;
  const { onMove, onResetPlacement } = props;
  // выбирать нечего — не показываем: стены и пол комнаты витрины (одна опция из паспорта отделки, demo-05 п.9) были в списке
  // покупателя как «wall»/«floor»
  const slots = apartment.slots.filter((s) => s.roomId === roomId && !(s.kind === "surface" && optionsForSlot(apartment, catalogue, s).length <= 1));
  const active: Slot | undefined = slots.find((s) => s.id === slotId) ?? slots[0];
  const options: Option[] = active ? optionsForSlot(apartment, catalogue, active) : [];
  const chosenId = active ? selections[active.id] ?? active.defaultOptionId : "";
  const current = options.find((o) => o.id === chosenId);

  // ширину ленты и всей полосы меряем по факту: от первой зависит, сколько плиток поместится крупными, от второй — раскладка
  const stripRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const [stripWidth, setStripWidth] = useState(600);
  const [rootWidth, setRootWidth] = useState(1000);
  useEffect(() => {
    const strip = stripRef.current;
    const root = rootRef.current;
    if (!strip || !root) return;
    const measure = () => {
      setStripWidth(strip.getBoundingClientRect().width);
      setRootWidth(root.getBoundingClientRect().width);
    };
    const ro = new ResizeObserver(measure);
    ro.observe(strip);
    ro.observe(root);
    measure();
    return () => ro.disconnect();
  }, []);
  // УЗКАЯ ПОЛОСА (телефон, flat3d-375-overlaps 21.10): меню слева и плитки справа делили 375 px пополам — от строки товара
  // оставалась одна буква, плитки и кнопки мест обрезались краем. На узкой — сверху строка «комната · места», ниже
  // строка товара с ✕ и один ряд плиток на всю ширину.
  const narrow = rootWidth < NARROW_PX;
  const { size: tileSize, rows: tileRows } = tileLayout(options.length, stripWidth, narrow);
  // картинка плитки — так, чтобы под ней влезли название и цена (≈41 px с полями): прежние 168/82 при ленте 172 px прятали
  // подпись и цену за нижним краем полосы (снимки 1440, 21.10)
  const tileHeight = narrow ? 72 : tileRows === 1 ? 148 : 52;

  // выбранное место — в видимую часть строки мест (выбор пришёл из сцены, а кнопка могла быть за краем прокрутки)
  const slotsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const box = slotsRef.current;
    const btn = box?.querySelector<HTMLElement>(`[data-slot="${active?.id ?? ""}"]`);
    if (!box || !btn || !narrow) return;
    box.scrollLeft = btn.offsetLeft - box.offsetLeft - (box.clientWidth - btn.offsetWidth) / 2;
  }, [active?.id, narrow]);

  const closeBtn = (
    <button
      type="button"
      onClick={onClose}
      aria-label={lang === "en" ? "Close" : "Закрыть"}
      className="min-h-11 min-w-11 shrink-0 self-start rounded-lg text-tertiary hover:bg-secondary"
    >
      ✕
    </button>
  );

  return (
    <div
      ref={rootRef}
      className="flex shrink-0 gap-2 rounded-xl bg-primary p-2 ring-1 ring-inset ring-secondary"
      style={narrow ? { flexDirection: "column", gap: 6 } : { height: 248 }}
      role="region"
      aria-label={lang === "en" ? "Build bar" : "Панель выбора"}
    >
      {/* МЕНЮ СЛЕВА: комната сверху, ниже — что меняем, кнопками в ДВА РЯДА (без прокрутки:
          владелец 30.09 — «прокрутку не надо, там влезет в два ряда кнопки»); на узкой полосе — одной строкой */}
      <div className={narrow ? "flex min-w-0 items-center gap-1.5" : "flex shrink-0 flex-col gap-1.5"} style={narrow ? undefined : { maxWidth: "46%" }}>
        <select
          aria-label={lang === "en" ? "Room" : "Комната"}
          value={roomId}
          onChange={(e) => onRoom(e.target.value)}
          className="min-h-11 rounded-lg bg-secondary px-2 text-sm font-medium text-primary"
          // название комнаты целиком («Гостиная 14.4 м²»): нативный список обрезает текст без многоточия
          style={narrow ? { flex: "none" } : undefined}
        >
          {apartment.rooms.map((r) => (
            <option key={r.id} value={r.id}>
              {lang === "en" ? r.titleEn : r.titleRu}
            </option>
          ))}
        </select>
        <div
          ref={slotsRef}
          className={narrow ? "flex min-w-0 flex-1 gap-1 overflow-x-auto" : "grid gap-1 overflow-x-auto"}
          style={narrow ? { scrollbarWidth: "none" } : { gridTemplateRows: "repeat(2, minmax(0, 1fr))", gridAutoFlow: "column", gridAutoColumns: "104px", maxHeight: 96 }}
        >
          {slots.map((s) => {
            const isActive = s.id === active?.id;
            return (
              <button
                key={s.id}
                type="button"
                data-slot={s.id}
                aria-pressed={isActive}
                onClick={() => onSlot(s.id)}
                className={`min-h-11 shrink-0 rounded-lg px-2 text-left leading-tight ${
                  isActive ? "bg-brand-solid text-white" : "bg-secondary text-secondary"
                }`}
                style={narrow ? { fontSize: 12, minHeight: 44, whiteSpace: "nowrap" } : { fontSize: 12, width: 104, minHeight: 44 }}
                title={`${categoryTitle(s.category, lang)} · ${lang === "en" ? s.titleEn : s.titleRu}`}
              >
                {lang === "en" ? s.titleEn : s.titleRu}
              </button>
            );
          })}
        </div>
        {narrow && !current ? closeBtn : null}
      </div>

      {/* ПЛИТКИ ВАРИАНТОВ: два ряда, прокрутка вбок */}
      <div className="min-w-0 flex-1" ref={stripRef}>
        {current ? (
          /* Строка над лентой: название с ценой (может обрезаться) и ДЕЙСТВИЯ отдельными
             кнопками. Раньше кнопки жили внутри той же обрезаемой строки и просто исчезали. */
          <div className="mb-1 flex items-center gap-2">
            <p className="min-w-0 flex-1 truncate text-xs text-tertiary">
              {lang === "en" ? current.titleEn : current.titleRu}
              {/* размер спрашивают чаще цены (план flat3d-sims-ux E4): Ш×Г×В модели, только из паспорта товара */}
              {current.asset.kind === "mesh" ? ` · ${Math.round(current.asset.wCm)}×${Math.round(current.asset.dCm)}×${Math.round(current.asset.hCm)} ${lang === "en" ? "cm" : "см"}` : ""}
              {/* ковёр — длина × ширина плиты товара (demo-18 п.2): замена ковра меняет размер на полу */}
              {current.asset.kind === "kit" && current.asset.wCm && current.asset.dCm
                ? ` · ${Math.round(Math.max(current.asset.wCm, current.asset.dCm))}×${Math.round(Math.min(current.asset.wCm, current.asset.dCm))} ${lang === "en" ? "cm" : "см"}`
                : ""}
              {current.listPrice ? ` · ${formatMoney(current.listPrice, catalogue.currency, lang)}` : ""}
              {current.shopUrl ? (
                <>
                  {" · "}
                  <a href={current.shopUrl} target="_blank" rel="noopener noreferrer nofollow" className="underline">
                    {lang === "en" ? "view in shop" : "смотреть в магазине"}
                  </a>
                </>
              ) : null}
            </p>
            {/* Передвинуть можно только отдельно стоящую мебель: кухня, шкаф и покрытия
                привязаны к стене и к комнате. */}
            {onMove && active && active.kind === "furniture" && !active.tabletop ? (
              <button
                type="button"
                onClick={() => onMove(active.id)}
                className="shrink-0 rounded-lg bg-secondary px-3 py-1 text-xs font-medium text-primary ring-1 ring-inset ring-secondary"
                style={{ minHeight: 32 }}
              >
                {lang === "en" ? "Move" : "Передвинуть"}
              </button>
            ) : null}
            {onResetPlacement ? (
              <button
                type="button"
                onClick={onResetPlacement}
                className="shrink-0 rounded-lg px-2 py-1 text-xs text-secondary"
                style={{ minHeight: 32 }}
              >
                {lang === "en" ? "Reset position" : "Вернуть на место"}
              </button>
            ) : null}
            {narrow ? closeBtn : null}
          </div>
        ) : null}
        {/* два ряда плиток, прокрутка вбок; ширина колонки задана жёстко, иначе одна длинная
            подпись растягивает всю колонку и в ленте появляются дыры */}
        <ul
          className="grid grid-flow-col gap-1.5 overflow-x-auto pb-1"
          style={{
            height: narrow ? 120 : 196,
            gridTemplateRows: `repeat(${tileRows}, minmax(0, 1fr))`,
            gridAutoColumns: `${tileSize}px`,
          }}
        >
          {options.map((o) => {
            const chosen = o.id === chosenId;
            return (
              <li key={o.id} style={{ width: tileSize }}>
                <button
                  type="button"
                  onClick={() => active && onChoose(active.id, o.id)}
                  aria-pressed={chosen}
                  style={{ width: tileSize }}
                  className={`rounded-lg p-1 text-left ring-1 ring-inset ${
                    chosen ? "bg-brand-primary ring-brand-solid" : "bg-secondary ring-secondary"
                  }`}
                >
                  <span
                    className="block w-full overflow-hidden rounded-md bg-primary"
                    /* картинка занимает почти всю плитку: при крупных плитках товар должно быть видно */
                    style={{ backgroundColor: tileColour(catalogue, o), height: tileHeight }}
                  >
                    {tileImage(catalogue, o) ? (
                      // eslint-disable-next-line @next/next/no-img-element -- превью товара или материала
                      <img src={tileImage(catalogue, o)} alt="" className="size-full object-cover" loading="lazy" />
                    ) : null}
                  </span>
                  <span className="mt-0.5 block truncate leading-tight text-primary" style={{ fontSize: 11 }}>
                    {lang === "en" ? o.titleEn : o.titleRu}
                  </span>
                  <span className="block font-semibold text-secondary" style={{ fontSize: 11 }}>
                    {o.tier === "base" || o.price === 0
                      ? lang === "en"
                        ? "included"
                        : "входит"
                      : `+${formatMoney(o.price, catalogue.currency, lang)}`}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      {narrow ? null : closeBtn}
    </div>
  );
}
