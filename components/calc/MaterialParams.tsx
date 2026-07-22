"use client";

import type { CalcKind, MaterialSpec } from "@/contracts/calc";
import { DIRECTION_LABEL, PAINT_TYPES, ROW_OFFSET_LABEL, SURFACE_TYPES } from "@/lib/estimate/defaults";
import { NumInput } from "./NumInput";

const inp = {
  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--base)",
  background: "var(--surface)", color: "var(--text)", fontSize: 15, width: "100%",
} as const;

// Плейсхолдер по умолчанию — «0» (светло-серый через CSS input::placeholder): видно, где заполнено.
function NumField({ label, value, onChange, ph = "0" }: { label: string; value: number | undefined; onChange: (v: number | undefined) => void; ph?: string }) {
  return (
    <label className="stack" style={{ flex: 1, minWidth: 120, gap: 4 }}>
      <span className="eyebrow">{label}</span>
      <NumInput style={inp} placeholder={ph} value={value} onChange={onChange} />
    </label>
  );
}

// Размеры плитки в СМ (люди указывают плитку в см: 60×120, 20×20). Хранение — в мм (контракт/формулы).
const mmToCm = (mm: number | undefined) => (mm == null ? undefined : Math.round(mm) / 10);
const cmToMm = (cm: number | undefined) => (cm == null ? undefined : Math.round(cm * 10));

// Цена плитки может быть за м² / за шт / за упаковку — одно поле + селектор единицы (одновременно
// задана ровно одна из трёх; смена единицы переносит значение и чистит остальные).
function TilePrice({ spec, onChange }: { spec: MaterialSpec; onChange: (patch: Partial<MaterialSpec>) => void }) {
  const unit: "m2" | "piece" | "pack" = spec.pricePerM2Rub != null ? "m2" : spec.pricePerPieceRub != null ? "piece" : "pack";
  const value = spec.pricePerM2Rub ?? spec.pricePerPieceRub ?? spec.pricePerPackRub;
  const write = (u: "m2" | "piece" | "pack", v: number | undefined) =>
    onChange({ pricePerM2Rub: u === "m2" ? v : undefined, pricePerPieceRub: u === "piece" ? v : undefined, pricePerPackRub: u === "pack" ? v : undefined });
  return (
    <div className="row" style={{ gap: 8 }}>
      <NumField label="Цена, ₽" value={value} onChange={(v) => write(unit, v)} />
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
export function MaterialParams({ kind, spec, onChange }: { kind: CalcKind; spec: MaterialSpec; onChange: (patch: Partial<MaterialSpec>) => void }) {
  return (
    <div className="stack" style={{ gap: 8 }}>
      <p className="eyebrow" style={{ margin: 0 }}>Параметры материала</p>

      {kind === "oboi" && (
        <>
          <div className="row" style={{ gap: 8 }}>
            <NumField label="Ширина рулона, м" value={spec.rollWidthM} onChange={(v) => onChange({ rollWidthM: v })} />
            <NumField label="Длина рулона, м" value={spec.rollLengthM} onChange={(v) => onChange({ rollLengthM: v })} />
          </div>
          <div className="row" style={{ gap: 8 }}>
            <NumField label="Раппорт, м" value={spec.rapportM} onChange={(v) => onChange({ rapportM: v })} />
            <NumField label="Цена/рулон, ₽" value={spec.pricePerRollRub} onChange={(v) => onChange({ pricePerRollRub: v })} />
          </div>
          <label className="row" style={{ gap: 8, alignItems: "center" }}>
            <input type="checkbox" checked={!!spec.offset} onChange={(e) => onChange({ offset: e.target.checked })} />
            <span>Укладка со смещением рисунка</span>
          </label>
        </>
      )}

      {kind === "plitka" && (
        <>
          <div className="row" style={{ gap: 8 }}>
            <NumField label="Длина плитки, см" value={mmToCm(spec.tileLengthMm)} onChange={(v) => onChange({ tileLengthMm: cmToMm(v) })} />
            <NumField label="Ширина плитки, см" value={mmToCm(spec.tileWidthMm)} onChange={(v) => onChange({ tileWidthMm: cmToMm(v) })} />
          </div>
          <div className="row" style={{ gap: 8 }}>
            <NumField label="Шов, мм" value={spec.seamMm} onChange={(v) => onChange({ seamMm: v })} />
            <NumField label="Шт/упаковка" value={spec.tilesPerPack} onChange={(v) => onChange({ tilesPerPack: v })} />
          </div>
          <TilePrice spec={spec} onChange={onChange} />
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
            <NumField label="Расход, м²/л" value={spec.consumptionM2PerL} onChange={(v) => onChange({ consumptionM2PerL: v })} />
            <NumField label="Объём упак, л" value={spec.packVolumeL} onChange={(v) => onChange({ packVolumeL: v })} />
            <NumField label="Цена упак, ₽" value={spec.pricePerPackRub} onChange={(v) => onChange({ pricePerPackRub: v })} />
          </div>
        </>
      )}

      {kind === "laminat" && (
        <>
          <div className="row" style={{ gap: 8 }}>
            <NumField label="Длина панели, мм" value={spec.panelLengthMm} onChange={(v) => onChange({ panelLengthMm: v })} />
            <NumField label="Ширина панели, мм" value={spec.panelWidthMm} onChange={(v) => onChange({ panelWidthMm: v })} />
            <NumField label="Шт/упаковка" value={spec.panelsPerPack} onChange={(v) => onChange({ panelsPerPack: v })} />
          </div>
          <div className="row" style={{ gap: 8 }}>
            <label className="stack" style={{ flex: 1, minWidth: 140, gap: 4 }}>
              <span className="eyebrow">Направление укладки</span>
              <select style={inp} value={spec.direction ?? "length"} onChange={(e) => onChange({ direction: e.target.value as MaterialSpec["direction"] })}>
                {(Object.keys(DIRECTION_LABEL) as Array<keyof typeof DIRECTION_LABEL>).map((k) => <option key={k} value={k}>{DIRECTION_LABEL[k]}</option>)}
              </select>
            </label>
            <label className="stack" style={{ flex: 1, minWidth: 120, gap: 4 }}>
              <span className="eyebrow">Смещение рядов</span>
              <select style={inp} value={spec.rowOffset ?? "third"} onChange={(e) => onChange({ rowOffset: e.target.value as MaterialSpec["rowOffset"] })}>
                {(Object.keys(ROW_OFFSET_LABEL) as Array<keyof typeof ROW_OFFSET_LABEL>).map((k) => <option key={k} value={k}>{ROW_OFFSET_LABEL[k]}</option>)}
              </select>
            </label>
            <NumField label="Цена/упак, ₽" value={spec.pricePerPackRub} onChange={(v) => onChange({ pricePerPackRub: v })} />
          </div>
        </>
      )}
    </div>
  );
}
