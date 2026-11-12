"use client";

// Рабочая часть /lab/mesh-check: шапка с итогами, разделы, фильтр, карточки страницы, «дальше» и окно увеличения. Карточки и
// счётчики живут в состоянии вкладки: нажатие сразу меняет «проверено N из M», без перезагрузки страницы.

import Link from "next/link";
import { useCallback, useState } from "react";
import { isChecked } from "@/lib/mesh-audit/marks";
import type { CheckFilter } from "@/lib/mesh-audit/repo-check";
import type { SectionCount } from "@/lib/mesh-audit/sections";
import type { AuditItemView } from "@/lib/mesh-audit/types";
import { MeshCheckCard, type ZoomWhich } from "./MeshCheckCard";
import { checkHref, MeshCheckFilter, MeshCheckTabs, MeshCheckTop } from "./MeshCheckNav";
import { MeshCheckZoom } from "./MeshCheckZoom";

interface Props {
  items: AuditItemView[];
  counts: SectionCount[];
  section: string;
  filter: CheckFilter;
  page: number;
  pages: number;
  modelUrls: Record<number, string | null>;
}

const EMPTY: Record<CheckFilter, string> = {
  all: "В этом разделе моделей пока нет.",
  todo: "Здесь всё проверено.",
  bad: "Брака в этом разделе нет.",
};

export function MeshCheckBoard({ items: initial, counts: initialCounts, section, filter, page, pages, modelUrls }: Props) {
  const [items, setItems] = useState(initial);
  const [counts, setCounts] = useState(initialCounts);
  const [zoom, setZoom] = useState<{ i: number; which: ZoomWhich } | null>(null);

  const onChange = useCallback(
    (it: AuditItemView) => {
      const old = items.find((x) => x.id === it.id);
      const d = old ? Number(isChecked(it)) - Number(isChecked(old)) : 0;
      if (d) setCounts((cs) => cs.map((c) => (c.key === section ? { ...c, checked: c.checked + d } : c)));
      setItems((prev) => prev.map((x) => (x.id === it.id ? it : x)));
    },
    [items, section],
  );
  const onNav = useCallback((step: -1 | 1) => setZoom((z) => (z ? { ...z, i: Math.min(items.length - 1, Math.max(0, z.i + step)) } : z)), [items.length]);
  const onClose = useCallback(() => setZoom(null), []);
  const cur = zoom ? items[zoom.i] : undefined;

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-5">
      <MeshCheckTop counts={counts} />
      <MeshCheckTabs counts={counts} section={section} />
      <MeshCheckFilter count={counts.find((c) => c.key === section)} section={section} filter={filter} />
      {items.length === 0 ? (
        <p className="py-10 text-center text-sm text-tertiary">{EMPTY[filter]}</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {items.map((it, i) => (
            <MeshCheckCard key={`${it.id}:${it.generationKey}`} item={it} onChange={onChange} onZoom={(which) => setZoom({ i, which })} />
          ))}
        </div>
      )}
      {pages > 1 && (
        <nav className="flex items-center justify-center gap-2" aria-label="Страницы">
          {page > 1 && (
            <Link href={checkHref(section, filter, page - 1)} className="flex min-h-11 items-center rounded-lg bg-primary px-4 text-sm text-secondary ring-1 ring-primary ring-inset">
              ← назад
            </Link>
          )}
          <span className="text-sm text-tertiary">
            {page} из {pages}
          </span>
          {page < pages && (
            <Link href={checkHref(section, filter, page + 1)} className="flex min-h-11 items-center rounded-lg bg-primary px-4 text-sm text-secondary ring-1 ring-primary ring-inset">
              следующие 20 →
            </Link>
          )}
        </nav>
      )}
      {cur && zoom && (
        <MeshCheckZoom
          item={cur}
          which={zoom.which}
          modelUrl={modelUrls[cur.id] ?? null}
          onWhich={(which) => setZoom({ ...zoom, which })}
          onClose={onClose}
          onNav={onNav}
          onChange={onChange}
        />
      )}
    </main>
  );
}
