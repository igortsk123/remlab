"use client";

// Рабочая часть /lab/cutout-check: шапка с итогами, разделы, фильтр, карточки страницы, «дальше» и окно увеличения. Карточки и счётчик
// живут в состоянии вкладки: нажатие сразу меняет «проверено N из M» без перезагрузки.

import Link from "next/link";
import { useCallback, useState } from "react";
import { isChecked, L, type CheckFilter, type Counts } from "@/lib/cutout-check/rules";
import type { CutoutItemView, RoleCount } from "@/lib/cutout-check/types";
import { CutoutCheckCard, type ZoomTarget } from "./CutoutCheckCard";
import { checkHref, CutoutCheckFilter, CutoutCheckTabs, CutoutCheckTop } from "./CutoutCheckNav";
import { CutoutCheckZoom } from "./CutoutCheckZoom";

interface Props {
  run: string;
  items: CutoutItemView[];
  roles: RoleCount[];
  all: Counts;
  role: string | null;
  filter: CheckFilter;
  page: number;
  pages: number;
}

const BTN = "flex min-h-11 items-center rounded-lg bg-primary px-4 text-sm text-secondary ring-1 ring-primary ring-inset";

export function CutoutCheckBoard({ run, items: initial, roles: r0, all: a0, role, filter, page, pages }: Props) {
  const [items, setItems] = useState(initial);
  const [roles, setRoles] = useState(r0);
  const [all, setAll] = useState(a0);
  const [zoom, setZoom] = useState<ZoomTarget | null>(null);

  const onChange = useCallback(
    (it: CutoutItemView) => {
      const old = items.find((x) => x.id === it.id);
      const d = old ? Number(isChecked(it)) - Number(isChecked(old)) : 0;
      const b = old ? Number(it.mark === "bad") - Number(old.mark === "bad") : 0;
      if (d || b) {
        setAll((a) => ({ ...a, checked: a.checked + d, bad: a.bad + b }));
        setRoles((rs) => rs.map((c) => (c.role === (it.role ?? "—") ? { ...c, checked: c.checked + d, bad: c.bad + b } : c)));
      }
      setItems((prev) => prev.map((x) => (x.id === it.id ? it : x)));
    },
    [items],
  );
  const close = useCallback(() => setZoom(null), []);

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-5">
      <CutoutCheckTop all={all} run={run} />
      <CutoutCheckTabs roles={roles} role={role} filter={filter} />
      <CutoutCheckFilter role={role} filter={filter} />
      {items.length === 0 ? (
        <p className="py-10 text-center text-sm text-tertiary">
          {L.empty.ru} / {L.empty.en}
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-3">
          {items.map((it) => (
            <CutoutCheckCard key={`${it.id}:${it.generationKey}`} item={it} onChange={onChange} onZoom={setZoom} />
          ))}
        </div>
      )}
      {pages > 1 && (
        <nav className="flex items-center justify-center gap-2" aria-label="Страницы / Pages">
          {page > 1 && (
            <Link href={checkHref(role, filter, page - 1)} className={BTN}>
              ← {L.prev.ru} / {L.prev.en}
            </Link>
          )}
          <span className="text-sm text-tertiary">
            {page} {L.of.ru} {pages}
          </span>
          {page < pages && (
            <Link href={checkHref(role, filter, page + 1)} className={BTN}>
              {L.next.ru} / {L.next.en} →
            </Link>
          )}
        </nav>
      )}
      {zoom && <CutoutCheckZoom target={zoom} onClose={close} />}
    </main>
  );
}
