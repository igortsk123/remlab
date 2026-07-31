"use client";

import { useState } from "react";
import { COMPANIONS, type CalcKind } from "@/lib/estimate/companions";
import { computeRoomParts } from "@/lib/calc/formulas";
import { pluralUnit } from "@/lib/format/plural";
import { Button } from "@/components/base/buttons/button";
import { Chip } from "@/components/base/chip/chip";
import { useCalcProject } from "./useCalcProject";
import { RoomPanel } from "./RoomPanel";
import { ResultView } from "./ResultView";
import { VizCta } from "./VizCta";

const round2 = (n: number) => Math.round(n * 100) / 100;
// Чьи размеры просим в пустом состоянии («заполните размеры …»).
const SIZE_ASK: Record<CalcKind, string> = { oboi: "стены", kraska: "стены", plitka: "стены или пола", laminat: "пола" };
// Визуализация по фото — раздел за заглушкой до запуска (launch-p1); баннер скрыт тем же флагом.
const SHOW_WIP = process.env.NEXT_PUBLIC_SHOW_WIP === "1";

// Билдер калькулятора v2: мультикомната (К0) + геометрия (К1) + параметры/формулы (К2) + итог/смета (К3).
export function CalcBuilder({ kind }: { kind: CalcKind }) {
  const { project, add, remove, update, clear } = useCalcProject(kind);
  const [activeId, setActiveId] = useState<string | null>(null);

  const activeIdSafe =
    activeId && project.rooms.some((r) => r.id === activeId) ? activeId : project.rooms[0]?.id ?? null;
  const active = project.rooms.find((r) => r.id === activeIdSafe) ?? null;
  const allParts = project.rooms.flatMap((r) => computeRoomParts(r, kind));
  const totalNet = round2(allParts.reduce((s, p) => s + p.out.areaNetM2, 0));
  const totalCost = allParts.reduce((s, p) => s + (p.out.costRub ?? 0), 0);
  // Суммарное количество материала (плитка → шт): части с известным размером (без qtyUnknown), по общей единице.
  const counted = allParts.filter((p) => !p.out.qtyUnknown && p.out.qty > 0);
  const qtyUnit = counted[0]?.out.unit;
  const totalQty = round2(counted.filter((p) => p.out.unit === qtyUnit).reduce((s, p) => s + p.out.qty, 0));
  // Размеры есть, но материал не задан → зовём указать материал, а не цену (количество ещё не считаем).
  const needMaterial = allParts.some((p) => p.out.qtyUnknown && p.out.areaNetM2 > 0);

  return (
    <div className="stack">
      <div className="calc-sticky">
        {/* Состав строки постоянный на всех стадиях (Площадь · Нужно · призыв) — меняются только
            значения: неизвестное показываем как «?», не как 0 (ноль читается как результат). */}
        <span className="eyebrow" style={{ margin: 0 }}>Итог</span>
        <span>Площадь: <strong>{totalNet > 0 ? `${totalNet} м²` : "?"}</strong></span>
        {qtyUnit && totalQty > 0 ? (
          <span>Нужно: <strong>{totalQty} {pluralUnit(qtyUnit, totalQty)}</strong></span>
        ) : (
          <span>Нужно: <strong>?</strong></span>
        )}
        {totalCost > 0 && <span>≈ <strong>{totalCost.toLocaleString("ru-RU")} ₽</strong></span>}
        {/* Призыв «что дальше» — по стадии. */}
        {totalNet <= 0 ? (
          <span className="muted" style={{ fontSize: 13 }}>→ заполните размеры {SIZE_ASK[kind]}</span>
        ) : needMaterial ? (
          <span className="muted" style={{ fontSize: 13 }}>→ вставьте ссылку или задайте параметры материала</span>
        ) : totalCost <= 0 ? (
          <span className="muted" style={{ fontSize: 13 }}>→ укажите цену товара, чтобы увидеть стоимость</span>
        ) : null}
      </div>

      <div className="row" style={{ gap: 8 }}>
        {project.rooms.map((r) => (
          <Chip key={r.id} isSelected={r.id === activeIdSafe} onChange={() => setActiveId(r.id)}>
            {r.name}
          </Chip>
        ))}
        <Button type="button" color="secondary" size="sm" className="rounded-full" onClick={add}>+ Комната</Button>
        <span className="spacer" />
        <Button
          type="button"
          color="link-gray"
          size="sm"
          className="self-center underline"
          onClick={() => { if (window.confirm("Начать новый расчёт? Текущий черновик будет очищен.")) clear(); }}
        >
          новый расчёт
        </Button>
      </div>

      {active && (
        <RoomPanel
          key={active.id}
          room={active}
          kind={kind}
          canDelete={project.rooms.length > 1}
          onUpdate={(fn) => update(active.id, fn)}
          onDelete={() => {
            remove(active.id);
            setActiveId(null);
          }}
        />
      )}

      {project.rooms.length > 1 && (
        <p className="muted" style={{ fontSize: 14 }}>
          Итого по {project.rooms.length} комнатам: {totalNet} м²
        </p>
      )}

      <ResultView project={project} />

      <div className="card stack">
        <p className="eyebrow">Также не забудьте</p>
        <ul className="checklist">
          {COMPANIONS[kind].map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </div>

      {SHOW_WIP && <VizCta />}
    </div>
  );
}
