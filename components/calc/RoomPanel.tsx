"use client";

import type { CalcKind, Floor, MaterialSpec, Room } from "@/contracts/calc";
import { computeRoomParts } from "@/lib/calc/formulas";
import { pluralUnit } from "@/lib/format/plural";
import { FloorEditor } from "./FloorEditor";
import { LinkAutofill } from "./LinkAutofill";
import { MaterialParams } from "./MaterialParams";
import { SurfaceEditor } from "./SurfaceEditor";

const EMPTY_FLOOR: Floor = { lengthM: 0, widthM: 0, extraZones: [], excludedZones: [] };

const nameInputStyle = {
  font: "inherit", fontWeight: 600, fontSize: 16,
  border: "1px solid var(--base)", borderRadius: 8,
  background: "var(--surface)", color: "var(--text)", padding: "6px 10px", maxWidth: 240,
} as const;

// Панель активной комнаты: имя, геометрия по виду, параметры материала, вычисленный результат.
// Плитка может иметь две части — стены и пол (каждая со своей плиткой: ссылка + параметры).
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

  // Блок материала: автозаполнение по ссылке + параметры (переиспользуется для стен, пола, прочих видов).
  const materialBlock = (spec: MaterialSpec, url: string | undefined, onSpec: (p: Partial<MaterialSpec>) => void, onUrl: (u: string) => void) => (
    <>
      <div className="divider" />
      <LinkAutofill kind={kind} url={url} onSpec={onSpec} onUrl={onUrl} />
      <MaterialParams kind={kind} spec={spec} onChange={onSpec} />
    </>
  );

  const wallEditor = (
    <SurfaceEditor
      surfaces={room.surfaces}
      onChange={(s) => onUpdate((r) => ({ ...r, surfaces: s }))}
      kind={kind}
      countOpenings={room.countOpenings}
      onCountOpenings={(v) => onUpdate((r) => ({ ...r, countOpenings: v }))}
    />
  );
  const wallMaterial = materialBlock(room.material, room.productUrl, setMaterial, (url) => onUpdate((r) => ({ ...r, productUrl: url })));

  return (
    <div className="card stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
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
          <FloorEditor floor={room.floor ?? EMPTY_FLOOR} onChange={(f) => onUpdate((r) => ({ ...r, floor: f }))} />
          {wallMaterial}
        </>
      ) : kind === "plitka" ? (
        <>
          {room.floor && <p className="eyebrow" style={{ margin: 0 }}>Стены</p>}
          {wallEditor}
          {wallMaterial}
          {!room.floor ? (
            <>
              <div className="divider" />
              <button type="button" className="chip" style={{ background: "var(--accent)", color: "var(--surface)", borderColor: "var(--accent)" }} onClick={() => onUpdate((r) => ({ ...r, floor: EMPTY_FLOOR }))}>+ добавить размеры пола</button>
            </>
          ) : (
            <>
              <div className="divider" />
              <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                <p className="eyebrow" style={{ margin: 0 }}>Пол</p>
                <button type="button" className="quiz-link" style={{ fontSize: 12 }} onClick={() => onUpdate((r) => ({ ...r, floor: undefined, floorMaterial: undefined, floorProductUrl: undefined }))}>удалить пол</button>
              </div>
              <FloorEditor floor={room.floor} onChange={(f) => onUpdate((r) => ({ ...r, floor: f }))} />
              {materialBlock(room.floorMaterial ?? {}, room.floorProductUrl, setFloorMaterial, (url) => onUpdate((r) => ({ ...r, floorProductUrl: url })))}
            </>
          )}
        </>
      ) : (
        <>
          {wallEditor}
          {wallMaterial}
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
