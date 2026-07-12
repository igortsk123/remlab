"use client";

import type { CalcKind, Floor, Room } from "@/contracts/calc";
import { roomAreas } from "@/lib/calc/geometry";
import { FloorEditor } from "./FloorEditor";
import { SurfaceEditor } from "./SurfaceEditor";

const EMPTY_FLOOR: Floor = { lengthM: 0, widthM: 0, extraZones: [], excludedZones: [] };

const nameInputStyle = {
  font: "inherit", fontWeight: 600, fontSize: 16,
  border: "1px solid var(--base)", borderRadius: 8,
  background: "var(--surface)", color: "var(--text)", padding: "6px 10px", maxWidth: 240,
} as const;

// Панель активной комнаты: имя, редактор геометрии по виду, вычисленная площадь.
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
  const areas = roomAreas(room, kind);
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

      <div className="note">
        Площадь: <strong>{areas.netM2} м²</strong>
        {areas.grossM2 !== areas.netM2 ? ` (без проёмов; всего ${areas.grossM2} м²)` : ""}
      </div>
    </div>
  );
}
