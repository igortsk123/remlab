"use client";

import type { CalcKind, MaterialSpec } from "@/contracts/calc";
import { DIRECTION_LABEL, PAINT_TYPES, ROW_OFFSET_LABEL, SURFACE_TYPES } from "@/lib/estimate/defaults";
import { NumInput } from "./NumInput";

const inp = {
  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--base)",
  background: "var(--surface)", color: "var(--text)", fontSize: 15, width: "100%",
} as const;

// Плейсхолдер по умолчанию — «0» (светло-серый через CSS input::placeholder): видно, где заполнено.
// tip — необязательная «?»-подсказка рядом с лейблом (hover/фокус-тап, как у иконки-двери обоев).
function NumField({ label, value, onChange, ph = "0", tip, auto }: { label: string; value: number | undefined; onChange: (v: number | undefined) => void; ph?: string; tip?: string; auto?: boolean }) {
  return (
    <label className="stack" style={{ flex: 1, minWidth: 120, gap: 4 }}>
      <span className="eyebrow">
        {label}
        {auto && value != null && <span className="auto-badge" title="Заполнено из ссылки; правьте — станет вашим значением">авто</span>}
        {tip && (
          <span className="help" tabIndex={0} role="note" aria-label={tip} data-tip={tip} style={{ marginLeft: 6, textTransform: "none", letterSpacing: 0 }}>?</span>
        )}
      </span>
      <NumInput style={inp} placeholder={ph} value={value} onChange={onChange} />
    </label>
  );
}

// Тексты «?»-подсказок (простым языком; показываются по hover/тапу через CSS-паттерн .help).
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
        <select style={inp} value={unit} onChange={(e) => write(e.target.value as "m2" | "piece" | "pack", value)}>
          <option value="m2">за м²</option>
          <option value="pack">за упаковку</option>
          <option value="piece">за шт</option>
        </select>
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
            <label className="row" style={{ gap: 8, alignItems: "center" }}>
              <input type="checkbox" checked={!!spec.offset} onChange={(e) => onChange({ offset: e.target.checked })} />
              <span>Стыковка рисунка со смещением</span>
            </label>
            <span className="help" tabIndex={0} role="note" aria-label={OFFSET_TIP} data-tip={OFFSET_TIP}>?</span>
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
              <select style={inp} value={spec.surfaceType ?? ""} onChange={(e) => onChange({ surfaceType: e.target.value || undefined })}>
                <option value="">—</option>
                {SURFACE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="stack" style={{ flex: 1, minWidth: 140, gap: 4 }}>
              <span className="eyebrow">Тип краски</span>
              <select style={inp} value={spec.paintType ?? ""} onChange={(e) => onChange({ paintType: e.target.value || undefined })}>
                <option value="">—</option>
                {PAINT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
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
              <select style={inp} value={spec.direction ?? "length"} onChange={(e) => onChange({ direction: e.target.value as MaterialSpec["direction"] })}>
                {(Object.keys(DIRECTION_LABEL) as Array<keyof typeof DIRECTION_LABEL>).map((k) => <option key={k} value={k}>{DIRECTION_LABEL[k]}</option>)}
              </select>
            </label>
            <label className="stack" style={{ flex: 1, minWidth: 120, gap: 4 }}>
              <span className="eyebrow">
                Смещение рядов
                <span className="help" tabIndex={0} role="note" aria-label={ROW_OFFSET_TIP} data-tip={ROW_OFFSET_TIP} style={{ marginLeft: 6, textTransform: "none", letterSpacing: 0 }}>?</span>
              </span>
              <select style={inp} value={spec.rowOffset ?? "third"} onChange={(e) => onChange({ rowOffset: e.target.value as MaterialSpec["rowOffset"] })}>
                {(Object.keys(ROW_OFFSET_LABEL) as Array<keyof typeof ROW_OFFSET_LABEL>).map((k) => <option key={k} value={k}>{ROW_OFFSET_LABEL[k]}</option>)}
              </select>
            </label>
            <NumField label="Цена за м², ₽" value={spec.pricePerM2Rub} onChange={(v) => onChange({ pricePerM2Rub: v })} auto={isAuto("pricePerM2Rub")} />
          </div>
        </>
      )}
    </div>
  );
}
