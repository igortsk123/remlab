"use client";

import { useEffect, useState } from "react";

// КНОПКИ У ВЫБРАННОГО ПРЕДМЕТА (план flat3d-sims-ux C1): «Заменить» и «Передвинуть» висят над предметом и едут за
// ним при движении камеры — не надо искать действие в нижней панели. Позиция — проекция центра предмета на экран
// (`viewer.projectSlot`), раз в кадр; предмет ушёл из вида — кнопки прячутся.
type Pos = { x: number; y: number; visible: boolean } | null;

export function ObjectTools({ project, onOptions, onMove, onRemove, labels }: {
  project: () => Pos;
  onOptions: () => void;
  onMove?: () => void;
  /** «Убрать» — только у мебели; вернуть — отменой или из правой панели. */
  onRemove?: () => void;
  labels: { options: string; move: string; remove: string };
}) {
  const [pos, setPos] = useState<Pos>(null);
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const p = project();
      setPos((old) => (!p || !old || Math.abs(p.x - old.x) > 1 || Math.abs(p.y - old.y) > 1 || p.visible !== old.visible ? p : old));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [project]);
  if (!pos || !pos.visible) return null;
  const btn = "min-h-11 rounded-lg bg-primary px-3 text-sm font-medium text-primary shadow-md ring-1 ring-inset ring-secondary";
  return (
    <div data-flat3d="object-tools" style={{ position: "absolute", left: pos.x, top: Math.max(8, pos.y - 70), transform: "translateX(-50%)", zIndex: 4, display: "flex", gap: 6 }}>
      <button type="button" className={btn} onClick={onOptions}>{labels.options}</button>
      {onMove ? <button type="button" className={btn} onClick={onMove}>{labels.move}</button> : null}
      {onRemove ? <button type="button" className={btn} onClick={onRemove}>{labels.remove}</button> : null}
    </div>
  );
}
