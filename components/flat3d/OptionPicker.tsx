"use client";

// Панель комнаты: категории → варианты. В комнате показываем ТОЛЬКО те категории, у которых
// в ней есть слот (требование ТЗ: не грузить покупателя чужими разделами).

import type { Apartment, Slot } from "@/contracts/apartment";
import type { Catalogue, Option } from "@/contracts/configurator";
import { optionsForSlot } from "@/lib/configurator/resolve";
import { categoryTitle, formatGbp, type Lang } from "@/lib/configurator/i18n";

interface OptionPickerProps {
  apartment: Apartment;
  catalogue: Catalogue;
  roomId: string;
  selections: Record<string, string>;
  selectedSlotId: string | null;
  onSelectSlot: (slotId: string) => void;
  onChoose: (slotId: string, optionId: string) => void;
  lang: Lang;
}

function tierBadge(o: Option, lang: Lang): string | null {
  if (o.tier === "premium") return lang === "en" ? "Premium" : "Премиум";
  if (o.packageName && o.tier !== "base") return o.packageName;
  return null;
}

export function OptionPicker(props: OptionPickerProps) {
  const { apartment, catalogue, roomId, selections, selectedSlotId, onSelectSlot, onChoose, lang } = props;
  const slots = apartment.slots.filter((s) => s.roomId === roomId);
  const active: Slot | undefined = slots.find((s) => s.id === selectedSlotId) ?? slots[0];
  if (!active) return null;
  const options = optionsForSlot(apartment, catalogue, active);
  const chosenId = selections[active.id] ?? active.defaultOptionId;

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap gap-1.5">
        {slots.map((s) => {
          const isActive = s.id === active.id;
          return (
            <button
              key={s.id}
              type="button"
              data-slot={s.id}
              aria-pressed={isActive}
              onClick={() => onSelectSlot(s.id)}
              className={`min-h-11 rounded-lg px-3 py-2 text-sm font-medium transition ${
                isActive
                  ? "bg-brand-solid text-white"
                  : "bg-primary text-secondary ring-1 ring-inset ring-secondary hover:bg-secondary"
              }`}
            >
              <span className="block uppercase opacity-70" style={{ fontSize: 11 }}>{categoryTitle(s.category, lang)}</span>
              {lang === "en" ? s.titleEn : s.titleRu}
            </button>
          );
        })}
      </div>

      <ul className="flex flex-1 flex-col gap-2 overflow-y-auto pr-1">
        {options.map((o) => {
          const isChosen = o.id === chosenId;
          const badge = tierBadge(o, lang);
          return (
            <li key={o.id}>
              <button
                type="button"
                onClick={() => onChoose(active.id, o.id)}
                aria-pressed={isChosen}
                className={`flex w-full items-center gap-3 rounded-xl p-2 text-left transition ${
                  isChosen ? "bg-brand-primary ring-2 ring-inset ring-brand-solid" : "bg-primary hover:bg-secondary ring-1 ring-inset ring-secondary"
                }`}
              >
                <span
                  className="size-14 shrink-0 overflow-hidden rounded-lg bg-secondary"
                  style={{ backgroundColor: swatch(catalogue, o) }}
                >
                  {preview(catalogue, o) ? (
                    // eslint-disable-next-line @next/next/no-img-element -- превью каталога и материалов, next/image в проекте не настроен
                    <img src={preview(catalogue, o)} alt="" className="size-full object-cover" loading="lazy" />
                  ) : null}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-primary">
                    {lang === "en" ? o.titleEn : o.titleRu}
                  </span>
                  {o.descRu ? <span className="block truncate text-xs text-tertiary">{o.descRu}</span> : null}
                  {badge ? (
                    <span className="mt-1 inline-block rounded-full bg-secondary px-2 py-0.5 text-secondary" style={{ fontSize: 11 }}>
                      {badge}
                    </span>
                  ) : null}
                </span>
                <span className="shrink-0 text-right text-sm font-semibold text-primary">
                  {o.tier === "base" || o.priceGbp === 0 ? (
                    <span className="text-xs font-normal text-tertiary">
                      {lang === "en" ? "included" : "входит"}
                    </span>
                  ) : (
                    `+${formatGbp(o.priceGbp, lang)}`
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Цвет плашки: у покрытия — сам материал, у мебели — нейтральный фон под фото. */
function swatch(c: Catalogue, o: Option): string | undefined {
  const asset = o.asset;
  if (asset.kind === "material") {
    const id = asset.materialId;
    return c.materials.find((m) => m.id === id)?.colorHex;
  }
  if (asset.kind === "kit") {
    const id = asset.materials.door ?? asset.materials.body;
    return id ? c.materials.find((m) => m.id === id)?.colorHex : undefined;
  }
  return undefined;
}

/** Картинка варианта: у мебели — фото товара, у покрытия — превью текстуры. */
function preview(c: Catalogue, o: Option): string | undefined {
  if (o.previewUrl) return o.previewUrl;
  const asset = o.asset;
  if (asset.kind === "material") {
    const id = asset.materialId;
    return c.materials.find((m) => m.id === id)?.previewUrl;
  }
  return undefined;
}
