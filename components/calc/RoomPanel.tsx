"use client";

import type { CalcKind, Floor, MaterialSpec, Room } from "@/contracts/calc";
import { computeRoomParts } from "@/lib/calc/formulas";
import { pluralUnit } from "@/lib/format/plural";
import { FloorEditor } from "./FloorEditor";
import { LinkAutofill } from "./LinkAutofill";
import { SurfaceEditor } from "./SurfaceEditor";

const EMPTY_FLOOR: Floor = { lengthM: 0, widthM: 0, extraZones: [], excludedZones: [] };
const greenChip = { background: "var(--accent)", color: "var(--surface)", borderColor: "var(--accent)" } as const;

const nameInputStyle = {
  font: "inherit", fontWeight: 600, fontSize: 16,
  border: "1px solid var(--base)", borderRadius: 8,
  background: "var(--surface)", color: "var(--text)", padding: "6px 10px", maxWidth: 240,
} as const;

// Панель активной комнаты: стек карточек. Материал (ссылка+параметры) — ОТДЕЛЬНОЙ карточкой ПЕРЕД
// размерами. Плитка может иметь две плитки (стены/пол), каждая — своя карточка ссылки + карточка размеров.
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
  const shown = parts.filter((p) => p.out.areaNetM2 > 0);
  const noteParts = shown.length ? shown : parts.slice(0, 1);

  const setMaterial = (patch: Partial<MaterialSpec>) => onUpdate((r) => ({ ...r, material: { ...r.material, ...patch } }));
  const setFloorMaterial = (patch: Partial<MaterialSpec>) => onUpdate((r) => ({ ...r, floorMaterial: { ...(r.floorMaterial ?? {}), ...patch } }));

  const wallLink = (
    <LinkAutofill kind={kind} url={room.productUrl} onUrl={(u) => onUpdate((r) => ({ ...r, productUrl: u }))} spec={room.material} onSpec={setMaterial} />
  );
  const wallSizes = (
    <div className="card stack">
      <SurfaceEditor
        surfaces={room.surfaces}
        onChange={(s) => onUpdate((r) => ({ ...r, surfaces: s }))}
        kind={kind}
        countOpenings={room.countOpenings}
        onCountOpenings={(v) => onUpdate((r) => ({ ...r, countOpenings: v }))}
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
        </>
      ) : kind === "plitka" ? (
        <>
          {room.floor && <p className="eyebrow" style={{ margin: "4px 0 -6px" }}>Стены</p>}
          {wallLink}
          {wallSizes}
          {!room.floor ? (
            <button type="button" className="chip" style={greenChip} onClick={() => onUpdate((r) => ({ ...r, floor: EMPTY_FLOOR }))}>+ добавить размеры пола</button>
          ) : (
            <>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginTop: 4 }}>
                <p className="eyebrow" style={{ margin: 0 }}>Пол</p>
                <button type="button" className="quiz-link" style={{ fontSize: 12 }} onClick={() => onUpdate((r) => ({ ...r, floor: undefined, floorMaterial: undefined, floorProductUrl: undefined }))}>удалить пол</button>
              </div>
              <LinkAutofill kind={kind} url={room.floorProductUrl} onUrl={(u) => onUpdate((r) => ({ ...r, floorProductUrl: u }))} spec={room.floorMaterial ?? {}} onSpec={setFloorMaterial} />
              <div className="card stack">
                <FloorEditor floor={room.floor} onChange={(f) => onUpdate((r) => ({ ...r, floor: f }))} />
              </div>
            </>
          )}
        </>
      ) : (
        <>
          {wallLink}
          {wallSizes}
        </>
      )}

      <div className="note">
        {noteParts.map((p, i) => (
          <div key={p.key} style={{ marginTop: i > 0 ? 10 : 0 }}>
            {p.label ? <div className="eyebrow" style={{ margin: 0 }}>{p.label}</div> : null}
            <div>
              Площадь: <strong>{p.out.areaNetM2} м²</strong>
              {p.out.areaGrossM2 !== p.out.areaNetM2 ? ` (без проёмов; всего ${p.out.areaGrossM2} м²)` : ""}
            </div>
            <div style={{ marginTop: 4 }}>
              Нужно: <strong>{p.out.qty} {pluralUnit(p.out.unit, p.out.qty)}</strong>
              {p.out.packs != null && p.out.unit !== "упаковка" ? ` · ${p.out.packs} упак.` : ""}
              {p.out.costRub != null ? ` · ~${p.out.costRub.toLocaleString("ru-RU")} ₽` : ""}
            </div>
            <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>{p.out.note}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
