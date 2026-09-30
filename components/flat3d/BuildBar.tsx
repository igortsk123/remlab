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
import { categoryTitle, formatGbp, type Lang } from "@/lib/configurator/i18n";

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
function tileLayout(count: number, width: number): { size: number; rows: 1 | 2 } {
  if (count === 0) return { size: 96, rows: 1 };
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
  const slots = apartment.slots.filter((s) => s.roomId === roomId);
  const active: Slot | undefined = slots.find((s) => s.id === slotId) ?? slots[0];
  const options: Option[] = active ? optionsForSlot(apartment, catalogue, active) : [];
  const chosenId = active ? selections[active.id] ?? active.defaultOptionId : "";
  const current = options.find((o) => o.id === chosenId);

  // ширину ленты меряем по факту: от неё зависит, сколько плиток поместится крупными
  const stripRef = useRef<HTMLDivElement>(null);
  const [stripWidth, setStripWidth] = useState(600);
  useEffect(() => {
    const el = stripRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setStripWidth(el.getBoundingClientRect().width));
    ro.observe(el);
    setStripWidth(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);
  const { size: tileSize, rows: tileRows } = tileLayout(options.length, stripWidth);
  const tileHeight = tileRows === 1 ? 168 : 82;

  return (
    <div
      className="flex shrink-0 gap-2 rounded-xl bg-primary p-2 ring-1 ring-inset ring-secondary"
      style={{ height: 212 }}
      role="region"
      aria-label={lang === "en" ? "Build bar" : "Панель выбора"}
    >
      {/* МЕНЮ СЛЕВА: комната сверху, ниже — что меняем, кнопками в ДВА РЯДА (без прокрутки:
          владелец 30.09 — «прокрутку не надо, там влезет в два ряда кнопки») */}
      <div className="flex shrink-0 flex-col gap-1.5" style={{ maxWidth: "46%" }}>
        <select
          aria-label={lang === "en" ? "Room" : "Комната"}
          value={roomId}
          onChange={(e) => onRoom(e.target.value)}
          className="min-h-11 rounded-lg bg-secondary px-2 text-sm font-medium text-primary"
        >
          {apartment.rooms.map((r) => (
            <option key={r.id} value={r.id}>
              {lang === "en" ? r.titleEn : r.titleRu}
            </option>
          ))}
        </select>
        <div
          className="grid gap-1 overflow-x-auto"
          style={{ gridTemplateRows: "repeat(2, minmax(0, 1fr))", gridAutoFlow: "column", gridAutoColumns: "104px", maxHeight: 96 }}
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
                className={`min-h-11 rounded-lg px-2 text-left leading-tight ${
                  isActive ? "bg-brand-solid text-white" : "bg-secondary text-secondary"
                }`}
                style={{ fontSize: 12, width: 104, minHeight: 44 }}
                title={`${categoryTitle(s.category, lang)} · ${lang === "en" ? s.titleEn : s.titleRu}`}
              >
                {lang === "en" ? s.titleEn : s.titleRu}
              </button>
            );
          })}
        </div>
      </div>

      {/* ПЛИТКИ ВАРИАНТОВ: два ряда, прокрутка вбок */}
      <div className="min-w-0 flex-1" ref={stripRef}>
        {current ? (
          /* Строка над лентой: название с ценой (может обрезаться) и ДЕЙСТВИЯ отдельными
             кнопками. Раньше кнопки жили внутри той же обрезаемой строки и просто исчезали. */
          <div className="mb-1 flex items-center gap-2">
            <p className="min-w-0 flex-1 truncate text-xs text-tertiary">
              {lang === "en" ? current.titleEn : current.titleRu}
              {current.listPriceGbp ? ` · ${formatGbp(current.listPriceGbp, lang)}` : ""}
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
            {onMove && active && active.kind === "furniture" ? (
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
                {lang === "en" ? "Back to plan" : "Вернуть на место"}
              </button>
            ) : null}
          </div>
        ) : null}
        {/* два ряда плиток, прокрутка вбок; ширина колонки задана жёстко, иначе одна длинная
            подпись растягивает всю колонку и в ленте появляются дыры */}
        <ul
          className="grid grid-flow-col gap-1.5 overflow-x-auto pb-1"
          style={{
            height: 172,
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
                    {o.tier === "base" || o.priceGbp === 0
                      ? lang === "en"
                        ? "included"
                        : "входит"
                      : `+${formatGbp(o.priceGbp, lang)}`}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      <button
        type="button"
        onClick={onClose}
        aria-label={lang === "en" ? "Close" : "Закрыть"}
        className="min-h-11 min-w-11 shrink-0 self-start rounded-lg text-tertiary hover:bg-secondary"
      >
        ✕
      </button>
    </div>
  );
}
