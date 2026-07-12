"use client";

import type { CalcKind, Floor, Room } from "@/contracts/calc";
import { computeRoom } from "@/lib/calc/formulas";
import { FloorEditor } from "./FloorEditor";
import { MaterialParams } from "./MaterialParams";
import { SurfaceEditor } from "./SurfaceEditor";

const EMPTY_FLOOR: Floor = { lengthM: 0, widthM: 0, extraZones: [], excludedZones: [] };

const nameInputStyle = {
  font: "inherit", fontWeight: 600, fontSize: 16,
  border: "1px solid var(--base)", borderRadius: 8,
  background: "var(--surface)", color: "var(--text)", padding: "6px 10px", maxWidth: 240,
} as const;

// Панель активной комнаты: имя, геометрия по виду, параметры материала, вычисленный результат.
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
  const out = computeRoom(room, kind);
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
        <FloorEditor floor={room.floor ?? EMPTY_FLOOR} onChange={(f) => onUpdate((r) => ({ ...r, floor: f }))} />
      ) : (
        <SurfaceEditor surfaces={room.surfaces} onChange={(s) => onUpdate((r) => ({ ...r, surfaces: s }))} />
      )}

      <MaterialParams
        kind={kind}
        spec={room.material}
        onChange={(patch) => onUpdate((r) => ({ ...r, material: { ...r.material, ...patch } }))}
      />

      <div className="note">
        <div>
          Площадь: <strong>{out.areaNetM2} м²</strong>
          {out.areaGrossM2 !== out.areaNetM2 ? ` (без проёмов; всего ${out.areaGrossM2} м²)` : ""}
        </div>
        <div style={{ marginTop: 4 }}>
          Нужно: <strong>{out.qty} {out.unit}</strong>
          {out.packs != null && out.unit !== "упаковка" ? ` · ${out.packs} упак.` : ""}
          {out.costRub != null ? ` · ~${out.costRub.toLocaleString("ru-RU")} ₽` : ""}
        </div>
        <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>{out.note}</div>
      </div>
    </div>
  );
}
