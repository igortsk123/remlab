"use client";

import type { CalcKind, MaterialSpec } from "@/contracts/calc";
import { DIRECTION_LABEL, PAINT_TYPES, ROW_OFFSET_LABEL, SURFACE_TYPES } from "@/lib/estimate/defaults";
import { Badge } from "@/components/base/badges/badges";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { NativeSelect } from "@/components/base/select/select-native";
import { Tooltip, TooltipTrigger } from "@/components/base/tooltip/tooltip";
import { NumInput } from "./NumInput";

// «?»-подсказка рядом с лейблом: UUI Tooltip (hover + фокус/тап — доступность из коробки).
function HelpTip({ tip }: { tip: string }) {
  return (
    <Tooltip title={tip} placement="bottom">
      <TooltipTrigger
        aria-label={tip}
        className="ml-1.5 inline-flex size-4 cursor-help items-center justify-center rounded-full text-xs font-semibold text-fg-quaternary ring-1 ring-secondary ring-inset hover:text-fg-tertiary"
      >
        ?
      </TooltipTrigger>
    </Tooltip>
  );
}

// Плейсхолдер по умолчанию — «0» (светло-серый плейсхолдер UUI): видно, где заполнено.
function NumField({ label, value, onChange, ph = "0", tip, auto }: { label: string; value: number | undefined; onChange: (v: number | undefined) => void; ph?: string; tip?: string; auto?: boolean }) {
  return (
    <label className="stack" style={{ flex: 1, minWidth: 120, gap: 4 }}>
      <span className="eyebrow">
        {label}
        {auto && value != null && (
          <span title="Заполнено из ссылки; правьте — станет вашим значением" className="ml-1.5 inline-block align-middle normal-case tracking-normal">
            <Badge type="pill-color" color="success" size="sm">авто</Badge>
          </span>
        )}
        {tip && <HelpTip tip={tip} />}
      </span>
      <NumInput placeholder={ph} value={value} onChange={onChange} ariaLabel={label} />
    </label>
  );
}

// Тексты «?»-подсказок (простым языком).
const OFFSET_TIP =
  "Способ стыковки полос — смотрите значок на этикетке рулона. «Прямая» стыковка: рисунок соседних " +
  "полос на одной высоте, галочка не нужна. «Со смещением» (значок со стрелками и цифрами, например " +
  "64/32): каждую следующую полосу сдвигают на полраппорта — обоев уйдёт немного больше.";
const ROW_OFFSET_TIP =
  "Насколько стык панелей в новом ряду сдвинут относительно предыдущего. «Произвольно» — ряд " +
  "начинают обрезком от прошлого: быстрее и почти без отходов. «1/2» — стык ровно посередине панели: " +
  "самый строгий рисунок, но отходов больше. «1/3» — «лесенка», золотая середина. На количество " +
  "упаковок почти не влияет — запас уже заложен в расчёт.";

// Размеры плитки в СМ (люди указывают плитку в см: 60×120, 20×20). Хранение — в мм (контракт/формулы).
const mmToCm = (mm: number | undefined) => (mm == null ? undefined : Math.round(mm) / 10);
const cmToMm = (cm: number | undefined) => (cm == null ? undefined : Math.round(cm * 10));

// Цена плитки может быть за м² / за шт / за упаковку — одно поле + селектор единицы (одновременно
// задана ровно одна из трёх; смена единицы переносит значение и чистит остальные).
function TilePrice({ spec, onChange, auto }: { spec: MaterialSpec; onChange: (patch: Partial<MaterialSpec>) => void; auto?: boolean }) {
  const unit: "m2" | "piece" | "pack" = spec.pricePerM2Rub != null ? "m2" : spec.pricePerPieceRub != null ? "piece" : "pack";
  const value = spec.pricePerM2Rub ?? spec.pricePerPieceRub ?? spec.pricePerPackRub;
  const write = (u: "m2" | "piece" | "pack", v: number | undefined) =>
    onChange({ pricePerM2Rub: u === "m2" ? v : undefined, pricePerPieceRub: u === "piece" ? v : undefined, pricePerPackRub: u === "pack" ? v : undefined });
  return (
    <div className="row" style={{ gap: 8 }}>
      <NumField label="Цена, ₽" value={value} onChange={(v) => write(unit, v)} auto={auto} />
      <label className="stack" style={{ flex: 1, minWidth: 120, gap: 4 }}>
        <span className="eyebrow">За единицу</span>
        <NativeSelect
          size="md"
          aria-label="За единицу"
          value={unit}
          onChange={(e) => write(e.target.value as "m2" | "piece" | "pack", value)}
          options={[
            { value: "m2", label: "за м²" },
            { value: "pack", label: "за упаковку" },
            { value: "piece", label: "за шт" },
          ]}
        />
      </label>
    </div>
  );
}

// Параметры материала по виду (К2). Пустые поля → формула берёт умные дефолты.
export function MaterialParams({ kind, spec, onChange, autoKeys }: { kind: CalcKind; spec: MaterialSpec; onChange: (patch: Partial<MaterialSpec>) => void; autoKeys?: string[] }) {
  const isAuto = (k: keyof MaterialSpec) => !!autoKeys?.includes(k as string);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <p className="eyebrow" style={{ margin: 0 }}>Параметры материала</p>

      {kind === "oboi" && (
        <>
          <div className="row" style={{ gap: 8 }}>
            <NumField label="Ширина рулона, м" value={spec.rollWidthM} onChange={(v) => onChange({ rollWidthM: v })} auto={isAuto("rollWidthM")} />
            <NumField label="Длина рулона, м" value={spec.rollLengthM} onChange={(v) => onChange({ rollLengthM: v })} auto={isAuto("rollLengthM")} />
          </div>
          <div className="row" style={{ gap: 8 }}>
            <NumField label="Раппорт, м" value={spec.rapportM} onChange={(v) => onChange({ rapportM: v })} auto={isAuto("rapportM")} tip="Раппорт — через сколько повторяется рисунок на обоях. Число указано на этикетке рулона, здесь вводится в метрах: 64 см = 0,64. Чем больше раппорт, тем больше обоев уходит на подгонку рисунка между полосами. Обои без подгонки рисунка — оставьте 0." />
            <NumField label="Цена/рулон, ₽" value={spec.pricePerRollRub} onChange={(v) => onChange({ pricePerRollRub: v })} auto={isAuto("pricePerRollRub")} />
          </div>
          <div className="row" style={{ gap: 6, alignItems: "center" }}>
            <Checkbox
              isSelected={!!spec.offset}
              onChange={(checked) => onChange({ offset: checked })}
              label="Стыковка рисунка со смещением"
            />
            <HelpTip tip={OFFSET_TIP} />
          </div>
        </>
      )}

      {kind === "plitka" && (
        <>
          <div className="row" style={{ gap: 8 }}>
            <NumField label="Длина плитки, см" value={mmToCm(spec.tileLengthMm)} onChange={(v) => onChange({ tileLengthMm: cmToMm(v) })} auto={isAuto("tileLengthMm")} />
            <NumField label="Ширина плитки, см" value={mmToCm(spec.tileWidthMm)} onChange={(v) => onChange({ tileWidthMm: cmToMm(v) })} auto={isAuto("tileWidthMm")} />
          </div>
          <div className="row" style={{ gap: 8 }}>
            <NumField label="Шов, мм" value={spec.seamMm} onChange={(v) => onChange({ seamMm: v })} tip="Шов — зазор между плитками, который заполняют затиркой. Стандарт 2–3 мм (крупная плитка — до 5 мм). Слегка уменьшает количество плиток." />
            <NumField label="Шт/упаковка" value={spec.tilesPerPack} onChange={(v) => onChange({ tilesPerPack: v })} auto={isAuto("tilesPerPack")} />
          </div>
          <TilePrice spec={spec} onChange={onChange} auto={isAuto("pricePerM2Rub") || isAuto("pricePerPieceRub") || isAuto("pricePerPackRub")} />
        </>
      )}

      {kind === "kraska" && (
        <>
          <div className="row" style={{ gap: 8 }}>
            <label className="stack" style={{ flex: 1, minWidth: 140, gap: 4 }}>
              <span className="eyebrow">Тип поверхности</span>
              <NativeSelect
                size="md"
                aria-label="Тип поверхности"
                value={spec.surfaceType ?? ""}
                onChange={(e) => onChange({ surfaceType: e.target.value || undefined })}
                options={[{ value: "", label: "—" }, ...SURFACE_TYPES.map((t) => ({ value: t, label: t }))]}
              />
            </label>
            <label className="stack" style={{ flex: 1, minWidth: 140, gap: 4 }}>
              <span className="eyebrow">Тип краски</span>
              <NativeSelect
                size="md"
                aria-label="Тип краски"
                value={spec.paintType ?? ""}
                onChange={(e) => onChange({ paintType: e.target.value || undefined })}
                options={[{ value: "", label: "—" }, ...PAINT_TYPES.map((t) => ({ value: t, label: t }))]}
              />
            </label>
          </div>
          <div className="row" style={{ gap: 8 }}>
            <NumField label="Слоёв" value={spec.coats} onChange={(v) => onChange({ coats: v })} />
            <NumField label="Расход, м²/л" value={spec.consumptionM2PerL} onChange={(v) => onChange({ consumptionM2PerL: v })} auto={isAuto("consumptionM2PerL")} />
            <NumField label="Объём упак, л" value={spec.packVolumeL} onChange={(v) => onChange({ packVolumeL: v })} auto={isAuto("packVolumeL")} />
            <NumField label="Цена упак, ₽" value={spec.pricePerPackRub} onChange={(v) => onChange({ pricePerPackRub: v })} auto={isAuto("pricePerPackRub")} />
          </div>
        </>
      )}

      {kind === "laminat" && (
        <>
          <div className="row" style={{ gap: 8 }}>
            <NumField label="Длина панели, мм" value={spec.panelLengthMm} onChange={(v) => onChange({ panelLengthMm: v })} auto={isAuto("panelLengthMm")} />
            <NumField label="Ширина панели, мм" value={spec.panelWidthMm} onChange={(v) => onChange({ panelWidthMm: v })} auto={isAuto("panelWidthMm")} />
            <NumField label="Шт/упаковка" value={spec.panelsPerPack} onChange={(v) => onChange({ panelsPerPack: v })} auto={isAuto("panelsPerPack")} />
          </div>
          <div className="row" style={{ gap: 8 }}>
            <label className="stack" style={{ flex: 1, minWidth: 140, gap: 4 }}>
              <span className="eyebrow">Направление укладки</span>
              <NativeSelect
                size="md"
                aria-label="Направление укладки"
                value={spec.direction ?? "length"}
                onChange={(e) => onChange({ direction: e.target.value as MaterialSpec["direction"] })}
                options={(Object.keys(DIRECTION_LABEL) as Array<keyof typeof DIRECTION_LABEL>).map((k) => ({ value: k, label: DIRECTION_LABEL[k] }))}
              />
            </label>
            <label className="stack" style={{ flex: 1, minWidth: 120, gap: 4 }}>
              <span className="eyebrow">
                Смещение рядов
                <HelpTip tip={ROW_OFFSET_TIP} />
              </span>
              <NativeSelect
                size="md"
                aria-label="Смещение рядов"
                value={spec.rowOffset ?? "third"}
                onChange={(e) => onChange({ rowOffset: e.target.value as MaterialSpec["rowOffset"] })}
                options={(Object.keys(ROW_OFFSET_LABEL) as Array<keyof typeof ROW_OFFSET_LABEL>).map((k) => ({ value: k, label: ROW_OFFSET_LABEL[k] }))}
              />
            </label>
            <NumField label="Цена за м², ₽" value={spec.pricePerM2Rub} onChange={(v) => onChange({ pricePerM2Rub: v })} auto={isAuto("pricePerM2Rub")} />
          </div>
        </>
      )}
    </div>
  );
}
