"use client";

import type { CalcKind, Opening, Surface } from "@/contracts/calc";
import { Button } from "@/components/base/buttons/button";
import { Tooltip, TooltipTrigger } from "@/components/base/tooltip/tooltip";
import { NumInput } from "./NumInput";

const uid = () => Math.random().toString(36).slice(2, 10);

const OPENINGS_NOTE =
  "Окна и двери не вычитаются из расчёта, т.к. обои клеятся целыми полосами, поэтому кусок, " +
  "оставшийся из-за проёма, обычно нельзя использовать в другом месте. За счёт этого получается " +
  "небольшой запас: на подгонку рисунка, обрезки и непредвиденные ошибки.";

// Иконка-«дверь» (прямоугольник + точка-ручка) — приглушённый подсказчик, почему проёмы не вводим
// (обои). Тултип раскрывается вправо (placement start): иконка у левого края блока.
function DoorHint() {
  return (
    <Tooltip title={OPENINGS_NOTE} placement="bottom start">
      <TooltipTrigger aria-label={OPENINGS_NOTE} className="inline-flex cursor-help items-center text-fg-quaternary hover:text-fg-tertiary">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
          <rect x="6" y="3" width="12" height="18" rx="1" />
          <circle cx="14.5" cy="12" r="1.1" fill="currentColor" stroke="none" />
        </svg>
      </TooltipTrigger>
    </Tooltip>
  );
}

// Редактор стен/поверхностей. Плитка/краска: у каждой стены можно добавить проёмы (окно/дверь,
// Ширина×Высота) — вычитаются из площади самим фактом ввода, без галочки-переключателя (ADR-0035).
// Обои: проёмы не вводятся — клеятся полосами, остаток идёт в запас (иконка-дверь объясняет).
export function SurfaceEditor({
  surfaces,
  onChange,
  kind,
  onAdd,
}: {
  surfaces: Surface[];
  onChange: (surfaces: Surface[]) => void;
  kind: CalcKind;
  onAdd?: () => void;
}) {
  const isOboi = kind === "oboi";
  const patch = (id: string, p: Partial<Surface>) =>
    onChange(surfaces.map((s) => (s.id === id ? { ...s, ...p } : s)));
  const patchOpenings = (sid: string, fn: (o: Opening[]) => Opening[]) =>
    onChange(surfaces.map((s) => (s.id === sid ? { ...s, openings: fn(s.openings) } : s)));
  // Высота первой стены подставляется остальным стенам, где высота ещё пустая (0). Каждую можно менять.
  const setHeight = (id: string, h: number) => {
    const isFirst = surfaces[0]?.id === id;
    onChange(surfaces.map((s) => {
      if (s.id === id) return { ...s, heightM: h };
      if (isFirst && s.heightM === 0) return { ...s, heightM: h };
      return s;
    }));
  };

  return (
    <div className="stack" style={{ gap: 12 }}>
      {surfaces.map((s, i) => (
        <div key={s.id} className="stack" style={{ gap: 8, borderLeft: "2px solid var(--border)", paddingLeft: 12 }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <span className="row" style={{ gap: 6, alignItems: "center", margin: 0 }}>
              <strong style={{ fontSize: 15 }}>{s.label || "Стена"}</strong>
              {/* Подсказка про проёмы общая — показываем один раз, у первой стены. */}
              {isOboi && i === 0 && <DoorHint />}
            </span>
            <Button type="button" color="link-gray" size="sm" className="text-xs underline" onClick={() => onChange(surfaces.filter((x) => x.id !== s.id))}>удалить</Button>
          </div>
          <div className="row" style={{ gap: 8 }}>
            <label className="stack" style={{ flex: 1, minWidth: 100, gap: 4 }}>
              <span className="eyebrow">Длина, м</span>
              <NumInput value={s.lengthM} onChange={(n) => patch(s.id, { lengthM: n ?? 0 })} />
            </label>
            <label className="stack" style={{ flex: 1, minWidth: 100, gap: 4 }}>
              <span className="eyebrow">Высота, м</span>
              <NumInput value={s.heightM} onChange={(n) => setHeight(s.id, n ?? 0)} />
            </label>
          </div>

          {/* Проёмы стены (плитка/краска): окно/дверь Ширина×Высота, вычитаются фактом ввода. */}
          {!isOboi && s.openings.map((o, oi) => (
            <div key={o.id} className="stack" style={{ gap: 8, borderLeft: "2px solid var(--accent)", paddingLeft: 10 }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                <strong style={{ fontSize: 14 }}>Проём {oi + 1}</strong>
                <Button type="button" color="link-gray" size="sm" className="text-xs underline" onClick={() => patchOpenings(s.id, (os) => os.filter((x) => x.id !== o.id))}>удалить</Button>
              </div>
              <div className="row" style={{ gap: 8 }}>
                <label className="stack" style={{ flex: 1, minWidth: 100, gap: 4 }}>
                  <span className="eyebrow">Ширина, м</span>
                  <NumInput value={o.widthM} onChange={(n) => patchOpenings(s.id, (os) => os.map((x) => (x.id === o.id ? { ...x, widthM: n ?? 0 } : x)))} />
                </label>
                <label className="stack" style={{ flex: 1, minWidth: 100, gap: 4 }}>
                  <span className="eyebrow">Высота, м</span>
                  <NumInput value={o.heightM} onChange={(n) => patchOpenings(s.id, (os) => os.map((x) => (x.id === o.id ? { ...x, heightM: n ?? 0 } : x)))} />
                </label>
              </div>
            </div>
          ))}
          {!isOboi && (
            <Button
              type="button"
              color="secondary"
              size="sm"
              className="self-start rounded-full"
              onClick={() => patchOpenings(s.id, (os) => [...os, { id: uid(), kind: "window", widthM: 0, heightM: 0, count: 1 }])}
            >
              + добавить проём
            </Button>
          )}
        </div>
      ))}

      {/* Следующая стена добавляется прямо из карточки размеров (RoomPanel показывает
          отдельную кнопку «+ добавить размеры стены» только пока стен нет). */}
      {onAdd && (
        <Button type="button" size="sm" className="self-start rounded-full" onClick={onAdd}>
          + добавить стену
        </Button>
      )}
    </div>
  );
}
