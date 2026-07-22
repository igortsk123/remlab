"use client";

import type { CalcKind, Floor, MaterialSpec, Room } from "@/contracts/calc";
import { computeRoomParts, type RoomPart } from "@/lib/calc/formulas";
import { pluralUnit } from "@/lib/format/plural";
import { FloorEditor } from "./FloorEditor";
import { LinkAutofill } from "./LinkAutofill";
import { LeadCard } from "./LeadCard";
import { SurfaceEditor } from "./SurfaceEditor";

const EMPTY_FLOOR: Floor = { lengthM: 0, widthM: 0, extraZones: [], excludedZones: [] };
const uid = () => Math.random().toString(36).slice(2, 10);

const nameInputStyle = {
  font: "inherit", fontWeight: 600, fontSize: 16,
  border: "1px solid var(--base)", borderRadius: 8,
  background: "var(--surface)", color: "var(--text)", padding: "6px 10px", maxWidth: 240,
} as const;

// Результат одной части (стены/пол/комната) — инлайн под своим блоком: Площадь + Нужно.
// Если у плитки не задан размер — в «Нужно» не площадь комнаты, а призыв задать размер/ссылку.
function PartNote({ part, label }: { part: RoomPart; label?: string }) {
  const o = part.out;
  const heading = label ?? part.label;
  const isFloor = part.key === "floor";
  return (
    <div className="note">
      {heading ? <div className="eyebrow" style={{ margin: 0 }}>{heading}</div> : null}
      {o.areaNetM2 <= 0 ? (
        <div className="muted">Введите размеры, чтобы посчитать площадь и количество.</div>
      ) : (
        <>
          <div>
            Площадь: <strong>{o.areaNetM2} м²</strong>
            {o.areaGrossM2 !== o.areaNetM2 ? ` (${isFloor ? "без учёта исключённых зон" : "без проёмов"}; всего ${o.areaGrossM2} м²)` : ""}
          </div>
          <div style={{ marginTop: 4 }}>
            Нужно:{" "}
            {o.qtyUnknown ? (
              <strong style={{ color: "var(--accent)" }}>? шт — задайте размер плитки или вставьте ссылку</strong>
            ) : (
              <>
                <strong>{o.qty} {pluralUnit(o.unit, o.qty)}</strong>
                {o.packs != null && o.unit !== "упаковка" ? ` · ${o.packs} упак.` : ""}
                {o.costRub != null ? ` · ~${o.costRub.toLocaleString("ru-RU")} ₽` : ""}
              </>
            )}
          </div>
          {/* Не дублируем призыв «задайте размер» — при неизвестном кол-ве note скрываем. */}
          {!o.qtyUnknown && <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>{o.note}</div>}
        </>
      )}
    </div>
  );
}

// Панель активной комнаты: стек карточек. Материал (ссылка+параметры) — ОТДЕЛЬНОЙ карточкой ПЕРЕД
// размерами. Плитка может иметь две плитки (стены/пол), каждая — своя карточка ссылки + карточка
// размеров, и свой результат инлайн под блоком.
export function RoomPanel({
  room,
  kind,
  canDelete,
  onUpdate,
  onDelete,
}: {
  room: Room;
  kind: CalcKind;
  canDelete: boolean;
  onUpdate: (fn: (r: Room) => Room) => void;
  onDelete: () => void;
}) {
  const parts = computeRoomParts(room, kind);
  const wallsPart = parts.find((p) => p.key === "walls");
  const floorPart = parts.find((p) => p.key === "floor");
  const mainPart = parts.find((p) => p.key === "main");

  const setMaterial = (patch: Partial<MaterialSpec>) => onUpdate((r) => ({ ...r, material: { ...r.material, ...patch } }));
  const setFloorMaterial = (patch: Partial<MaterialSpec>) => onUpdate((r) => ({ ...r, floorMaterial: { ...(r.floorMaterial ?? {}), ...patch } }));
  // Кнопка «+ добавить размеры стены» вынесена ИЗ карточки (стоит на фоне страницы, как «+ размеры пола»).
  const addWall = () => onUpdate((r) => ({ ...r, surfaces: [...r.surfaces, { id: uid(), label: `Стена ${r.surfaces.length + 1}`, lengthM: 0, heightM: r.surfaces[0]?.heightM ?? 0, openings: [] }] }));
  const addWallBtn = <button type="button" className="chip chip--accent" onClick={addWall}>+ добавить размеры стены</button>;

  const wallLink = (
    <>
      <LinkAutofill kind={kind} url={room.productUrl} onUrl={(u) => onUpdate((r) => ({ ...r, productUrl: u }))} spec={room.material} onSpec={setMaterial} />
      <LeadCard kind={kind} url={room.productUrl} />
    </>
  );
  const wallSizes = (
    <div className="card stack">
      <SurfaceEditor
        surfaces={room.surfaces}
        onChange={(s) => onUpdate((r) => ({ ...r, surfaces: s }))}
        kind={kind}
      />
    </div>
  );

  return (
    <div className="stack">
      <div className="card row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <input
          value={room.name}
          onChange={(e) => onUpdate((r) => ({ ...r, name: e.target.value }))}
          aria-label="Название комнаты"
          style={nameInputStyle}
        />
        {canDelete && <button type="button" className="quiz-link" onClick={onDelete}>Удалить</button>}
      </div>

      {kind === "laminat" ? (
        <>
          {wallLink}
          <div className="card stack">
            <FloorEditor floor={room.floor ?? EMPTY_FLOOR} onChange={(f) => onUpdate((r) => ({ ...r, floor: f }))} />
          </div>
          {mainPart && <PartNote part={mainPart} />}
        </>
      ) : kind === "plitka" ? (
        <>
          {room.floor && <p className="eyebrow" style={{ margin: "4px 0 -6px" }}>Стены</p>}
          {wallLink}
          {room.surfaces.length > 0 && wallSizes}
          {addWallBtn}
          {wallsPart && <PartNote part={wallsPart} label="Стены" />}
          {!room.floor ? (
            <button type="button" className="chip chip--accent" onClick={() => onUpdate((r) => ({ ...r, floor: EMPTY_FLOOR }))}>+ добавить размеры пола</button>
          ) : (
            <>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginTop: 4 }}>
                <p className="eyebrow" style={{ margin: 0 }}>Пол</p>
                <button type="button" className="quiz-link" onClick={() => onUpdate((r) => ({ ...r, floor: undefined, floorMaterial: undefined, floorProductUrl: undefined }))}>удалить пол</button>
              </div>
              <LinkAutofill kind={kind} url={room.floorProductUrl} onUrl={(u) => onUpdate((r) => ({ ...r, floorProductUrl: u }))} spec={room.floorMaterial ?? {}} onSpec={setFloorMaterial} />
              <LeadCard kind={kind} url={room.floorProductUrl} />
              <div className="card stack">
                <FloorEditor floor={room.floor} onChange={(f) => onUpdate((r) => ({ ...r, floor: f }))} />
              </div>
              {floorPart && <PartNote part={floorPart} label="Пол" />}
            </>
          )}
        </>
      ) : (
        <>
          {wallLink}
          {room.surfaces.length > 0 && wallSizes}
          {addWallBtn}
          {mainPart && <PartNote part={mainPart} />}
        </>
      )}
    </div>
  );
}
