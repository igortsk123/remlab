"use client";

// Карточка предмета прямо в сцене — «как в Sims» (владелец 29.09): кликнул по предмету —
// он подсветился, рядом всплыла карточка с ценой и ссылкой в магазин, кнопка «Заменить»
// раскрывает ленту вариантов, и замена видна сразу, не уходя из 3D.
//
// Позицию карточке диктует сцена (каждый кадр), поэтому двигаем её ЧЕРЕЗ REF, без ре-рендера:
// иначе React перерисовывал бы список вариантов 60 раз в секунду.

import { useCallback, useEffect, useRef, useState } from "react";

import type { Apartment, Slot } from "@/contracts/apartment";
import type { Catalogue, Option } from "@/contracts/configurator";
import { optionsForSlot } from "@/lib/configurator/resolve";
import { formatGbp, type Lang } from "@/lib/configurator/i18n";

export interface TrackedPoint {
  x: number;
  y: number;
  visible: boolean;
}

interface ItemCardProps {
  apartment: Apartment;
  catalogue: Catalogue;
  slotId: string;
  currentOptionId: string;
  lang: Lang;
  onChoose: (slotId: string, optionId: string) => void;
  onClose: () => void;
  /** Подписка на экранную позицию предмета; возвращает функцию отписки. */
  subscribe: (cb: (p: TrackedPoint) => void) => () => void;
}

export function ItemCard(props: ItemCardProps) {
  const { apartment, catalogue, slotId, currentOptionId, lang, onChoose, onClose, subscribe } = props;
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);

  const slot: Slot | undefined = apartment.slots.find((s) => s.id === slotId);
  const options: Option[] = slot ? optionsForSlot(apartment, catalogue, slot) : [];
  const current = options.find((o) => o.id === currentOptionId) ?? options[0];

  useEffect(() => {
    const un = subscribe((p) => {
      const el = boxRef.current;
      if (!el) return;
      // УДЕРЖИВАЕМ КАРТОЧКУ В КАДРЕ: предмет может быть у самого края или ниже экрана —
      // карточка тогда уезжала за границу канваса и читалась как «прилипла к углу».
      const host = el.parentElement;
      const W = host?.clientWidth ?? 0;
      const H = host?.clientHeight ?? 0;
      const w = el.offsetWidth;
      const h = el.offsetHeight;
      const x = Math.min(Math.max(p.x, w / 2 + 6), Math.max(w / 2 + 6, W - w / 2 - 6));
      const y = Math.min(Math.max(p.y, h + 10), Math.max(h + 10, H - 12));
      el.style.transform = `translate(-50%, -100%) translate(${Math.round(x)}px, ${Math.round(y)}px)`;
      el.style.opacity = p.visible ? "1" : "0";
      el.style.pointerEvents = p.visible ? "auto" : "none";
    });
    return un;
  }, [subscribe, slotId]);

  const cycle = useCallback(
    (dir: number) => {
      if (!slot || options.length === 0) return;
      const i = Math.max(0, options.findIndex((o) => o.id === currentOptionId));
      const next = options[(i + dir + options.length) % options.length]!;
      onChoose(slot.id, next.id);
    },
    [slot, options, currentOptionId, onChoose],
  );

  if (!slot || !current) return null;
  const title = lang === "en" ? current.titleEn : current.titleRu;
  const price = current.listPriceGbp ?? (current.priceGbp || 0);

  return (
    <div
      ref={boxRef}
      className="absolute left-0 top-0 z-10 rounded-xl bg-primary p-2.5 shadow-lg ring-1 ring-secondary transition-opacity"
      style={{ opacity: 0, width: "min(92vw, 320px)" }}
    >
      <div className="flex items-start gap-2">
        <span className="size-12 shrink-0 overflow-hidden rounded-lg bg-secondary">
          {current.previewUrl ? (
            // eslint-disable-next-line @next/next/no-img-element -- фото товара из каталога магазина
            <img src={current.previewUrl} alt="" className="size-full object-cover" />
          ) : null}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-primary">{lang === "en" ? slot.titleEn : slot.titleRu}</p>
          <p className="truncate text-xs text-tertiary">{title}</p>
          {price > 0 ? <p className="text-sm font-semibold text-primary">{formatGbp(price, lang)}</p> : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={lang === "en" ? "Close" : "Закрыть"}
          className="min-h-11 min-w-11 rounded-lg text-tertiary hover:bg-secondary"
        >
          ✕
        </button>
      </div>

      <div className="mt-2 flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => cycle(-1)}
          aria-label={lang === "en" ? "Previous option" : "Предыдущий вариант"}
          className="min-h-11 w-11 rounded-lg bg-secondary text-primary"
        >
          ‹
        </button>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="min-h-11 flex-1 rounded-lg bg-brand-solid px-3 text-sm font-semibold text-white"
        >
          {open ? (lang === "en" ? "Hide options" : "Свернуть") : lang === "en" ? "Change" : "Заменить"}
        </button>
        <button
          type="button"
          onClick={() => cycle(1)}
          aria-label={lang === "en" ? "Next option" : "Следующий вариант"}
          className="min-h-11 w-11 rounded-lg bg-secondary text-primary"
        >
          ›
        </button>
      </div>

      {current.shopUrl ? (
        <a
          href={current.shopUrl}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="mt-1.5 block truncate text-center text-xs text-secondary underline"
        >
          {lang === "en" ? "View in shop" : "Смотреть в магазине"}
          {current.shopName ? ` · ${current.shopName}` : ""}
        </a>
      ) : null}

      {open ? (
        <ul className="mt-2 flex gap-2 overflow-x-auto overflow-y-hidden pb-1" style={{ maxHeight: 176 }}>
          {options.map((o) => {
            const chosen = o.id === currentOptionId;
            return (
              <li key={o.id} className="shrink-0">
                <button
                  type="button"
                  onClick={() => onChoose(slot.id, o.id)}
                  aria-pressed={chosen}
                  style={{ width: 104 }}
                  className={`rounded-lg p-1 text-left ring-1 ring-inset ${
                    chosen ? "bg-brand-primary ring-brand-solid" : "bg-secondary ring-secondary"
                  }`}
                >
                  <span className="block h-16 w-full overflow-hidden rounded-md bg-primary">
                    {o.previewUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element -- превью товара/материала
                      <img src={o.previewUrl} alt="" className="size-full object-cover" loading="lazy" />
                    ) : null}
                  </span>
                  <span className="mt-1 block truncate leading-tight text-primary" style={{ fontSize: 11 }}>
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
      ) : null}
    </div>
  );
}
