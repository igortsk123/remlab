"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

import type { Zones } from "@/components/flat3d/Hotspots";

// КНОПКИ У ВЫБРАННОГО ПРЕДМЕТА (план flat3d-sims-ux C1): «Заменить» и «Передвинуть» висят над предметом и едут за
// ним при движении камеры — не надо искать действие в нижней панели. Позиция — проекция центра предмета на экран
// (`viewer.projectSlot`), раз в кадр; предмет ушёл из вида — кнопки прячутся.
// Меню держится ВНУТРИ свободной части кадра (flat3d-375-overlaps, 21.10): по ширине — не за краем, по высоте — между
// строкой кнопок сверху и стрелками снизу; на телефоне у стула внизу кадра оно ложилось на стрелки.
type Pos = { x: number; y: number; visible: boolean } | null;

const EDGE = 8;
const ABOVE = 70; // меню — над центром предмета

export function ObjectTools({ project, onOptions, onMove, onRemove, labels, zones }: {
  project: () => Pos;
  onOptions: () => void;
  onMove?: () => void;
  /** «Убрать» — только у мебели; вернуть — отменой или из правой панели. */
  onRemove?: () => void;
  labels: { options: string; move: string; remove: string };
  zones: Zones;
}) {
  const ref = useRef<HTMLDivElement>(null);
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
  // размеры меню и кадра — замером после отрисовки и при каждом изменении: при неподвижной камере иначе не было бы второго прохода
  const [size, setSize] = useState({ w: 0, h: 0, fw: 0, fh: 0 });
  const shown = !!pos?.visible;
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setSize((s) => {
      const n = { w: el.offsetWidth, h: el.offsetHeight, fw: el.parentElement?.clientWidth ?? 0, fh: el.parentElement?.clientHeight ?? 0 };
      return n.w === s.w && n.h === s.h && n.fw === s.fw && n.fh === s.fh ? s : n;
    });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    if (el.parentElement) ro.observe(el.parentElement);
    return () => ro.disconnect();
  }, [shown]);
  if (!pos || !pos.visible) return null;
  const { w, h, fw, fh } = size;
  // до первого замера — по центру над предметом, как раньше; дальше — зажать в свободную часть кадра
  const left = fw ? clamp(pos.x - w / 2, EDGE, fw - w - EDGE) : pos.x - w / 2;
  // над стрелками держимся, только если меню по ширине заходит на них (стрелки — по центру кадра)
  const overPad = !!zones.pad && left < (fw + zones.pad.w) / 2 && left + w > (fw - zones.pad.w) / 2;
  const bottom = Math.max(zones.bottom, overPad ? zones.pad!.h : 0);
  const top = fh ? clamp(pos.y - ABOVE, zones.top, fh - bottom - h) : Math.max(EDGE, pos.y - ABOVE);
  const btn = "min-h-11 rounded-lg bg-primary px-3 text-sm font-medium text-primary shadow-md ring-1 ring-inset ring-secondary";
  return (
    <div ref={ref} data-flat3d="object-tools" style={{ position: "absolute", left, top, zIndex: 6, display: "flex", gap: 6 }}>
      <button type="button" className={btn} onClick={onOptions}>{labels.options}</button>
      {onMove ? <button type="button" className={btn} onClick={onMove}>{labels.move}</button> : null}
      {onRemove ? <button type="button" className={btn} onClick={onRemove}>{labels.remove}</button> : null}
    </div>
  );
}

/** Зажать в [lo, hi]; если промежуток меньше меню — прижать к lo (левому или верхнему полю). */
function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}
