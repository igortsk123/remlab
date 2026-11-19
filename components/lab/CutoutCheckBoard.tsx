"use client";

// Рабочая часть /lab/cutout-check: шапка с итогами, разделы, фильтр, карточки страницы, «дальше» и окно увеличения. Карточки и счётчик
// живут в состоянии вкладки: просмотр и «не ок» сразу меняют «просмотрено N из M» без перезагрузки.

import Link from "next/link";
import { useCallback, useRef, useState } from "react";
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

  // всегда свежие карточки (запрос «просмотрено» может вернуться после нажатия «не ок»): считаем по ref, не по замыканию
  const cur = useRef(items);
  cur.current = items;
  const apply = useCallback((next: CutoutItemView) => {
    const old = cur.current.find((x) => x.id === next.id);
    const d = old ? Number(isChecked(next)) - Number(isChecked(old)) : 0;
    const b = old ? Number(next.mark === "bad") - Number(old.mark === "bad") : 0;
    if (d || b) {
      setAll((a) => ({ ...a, checked: a.checked + d, bad: a.bad + b }));
      setRoles((rs) => rs.map((c) => (c.role === (next.role ?? "—") ? { ...c, checked: c.checked + d, bad: c.bad + b } : c)));
    }
    cur.current = cur.current.map((x) => (x.id === next.id ? next : x));
    setItems(cur.current);
  }, []);
  const onView = useCallback(
    (id: number, generationKey: string) => {
      const old = cur.current.find((x) => x.id === id);
      if (old && old.generationKey === generationKey && !old.viewedAt) apply({ ...old, viewedAt: new Date().toISOString() });
    },
    [apply],
  );
  const onChange = apply;
  const close = useCallback(() => setZoom(null), []);

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-3">
      {/* сквозная шапка сайта на этой рабочей странице не нужна: на телефоне она съедает пол-экрана над карточкой */}
      <style>{".site-header{display:none}:root{--site-header-h:0px}"}</style>
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
            <CutoutCheckCard key={`${it.id}:${it.generationKey}`} item={it} onChange={onChange} onView={onView} onZoom={setZoom} />
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
