"use client";

// Режим «План»: вид сверху из той же разрешённой сцены, что и 3D.
//
// Поворот на экране — `rotate(-rot)`: ось y плана направлена ВНИЗ экрана, поэтому положительный
// (по часовой) поворот плана выглядит как обратный. Это ровно то же преобразование, что в демо
// (`flat215-demo/index.html:1616`), и трогать знак без замера нельзя.

import type { Apartment } from "@/contracts/apartment";
import type { ResolvedScene } from "@/lib/configurator/resolve";
import { surfacesByRoom } from "@/lib/viewer3d/build-scene";
import type { Lang } from "@/lib/configurator/i18n";

interface PlanViewProps {
  apartment: Apartment;
  scene: ResolvedScene;
  activeRoomId: string | null;
  selectedSlotId: string | null;
  onRoom: (roomId: string) => void;
  onSlot: (slotId: string) => void;
  lang: Lang;
}

const PAD = 40;

export function PlanView({ apartment, scene, activeRoomId, selectedSlotId, onRoom, onSlot, lang }: PlanViewProps) {
  const minX = Math.min(...apartment.rooms.map((r) => r.x));
  const minY = Math.min(...apartment.rooms.map((r) => r.y));
  const maxX = Math.max(...apartment.rooms.map((r) => r.x + r.w));
  const maxY = Math.max(...apartment.rooms.map((r) => r.y + r.d));
  const surfaces = surfacesByRoom(scene);

  return (
    <div className="h-full w-full overflow-auto rounded-xl bg-secondary p-2">
      <svg
        viewBox={`${minX - PAD} ${minY - PAD} ${maxX - minX + PAD * 2} ${maxY - minY + PAD * 2}`}
        className="h-full w-full"
        role="img"
        aria-label={lang === "en" ? "Floor plan" : "План квартиры"}
      >
        {apartment.rooms.map((room) => {
          const floor = surfaces.get(room.id)?.floor;
          const active = room.id === activeRoomId;
          return (
            <g key={room.id} onClick={() => onRoom(room.id)} style={{ cursor: "pointer" }}>
              <rect
                x={room.x}
                y={room.y}
                width={room.w}
                height={room.d}
                fill={floor?.material.colorHex ?? "var(--color-bg-secondary)"}
                stroke={active ? "var(--color-bg-brand-solid)" : "var(--color-border-secondary)"}
                strokeWidth={active ? 7 : 3}
              />
              <text
                x={room.x + room.w / 2}
                y={room.y + 26}
                textAnchor="middle"
                fontSize={22}
                fill="var(--color-text-primary)"
                style={{ pointerEvents: "none" }}
              >
                {lang === "en" ? room.titleEn : room.titleRu}
              </text>
              <text
                x={room.x + room.w / 2}
                y={room.y + 50}
                textAnchor="middle"
                fontSize={18}
                fill="var(--color-text-tertiary)"
                style={{ pointerEvents: "none" }}
              >
                {((room.w * room.d) / 10000).toFixed(1)} м²
              </text>
            </g>
          );
        })}

        {/* проёмы: белым по стене — чтобы план читался как план, а не как набор коробок */}
        {apartment.rooms.flatMap((room) =>
          room.openings.map((o, i) => {
            const t = 8;
            const fill = o.kind === "window" ? "var(--color-bg-brand-secondary)" : "var(--color-bg-primary)";
            const key = `${room.id}-${i}`;
            if (o.wall === "south" || o.wall === "north") {
              const y = o.wall === "south" ? room.y - t / 2 : room.y + room.d - t / 2;
              return <rect key={key} x={room.x + o.offsetCm} y={y} width={o.widthCm} height={t} fill={fill} />;
            }
            const x = o.wall === "west" ? room.x - t / 2 : room.x + room.w - t / 2;
            return <rect key={key} x={x} y={room.y + o.offsetCm} width={t} height={o.widthCm} fill={fill} />;
          }),
        )}

        {scene.items.map((item) => {
          const p = item.placement;
          const selected = item.slotId === selectedSlotId;
          return (
            <g
              key={item.slotId}
              transform={`translate(${p.x} ${p.y}) rotate(${-p.rot})`}
              onClick={(e) => {
                e.stopPropagation();
                onSlot(item.slotId);
              }}
              style={{ cursor: "pointer" }}
            >
              <rect
                x={-p.wCm / 2}
                y={-p.dCm / 2}
                width={p.wCm}
                height={p.dCm}
                rx={6}
                fill={selected ? "var(--color-bg-brand-primary)" : "var(--color-bg-primary)"}
                fillOpacity={0.92}
                stroke={selected ? "var(--color-bg-brand-solid)" : "var(--color-border-secondary)"}
                strokeWidth={selected ? 5 : 2.5}
              />
              {/* метка «лицо»: короткая черта у передней грани (перёд смотрит в +y) */}
              <line x1={-p.wCm / 4} y1={p.dCm / 2 - 4} x2={p.wCm / 4} y2={p.dCm / 2 - 4} stroke="var(--color-border-secondary)" strokeWidth={4} />
            </g>
          );
        })}
      </svg>
    </div>
  );
}
