"use client";

// Пагинация /lab/mesh-audit: назад/вперёд и прыжок на страницу (нативный select — ui-rules).

import { useRouter } from "next/navigation";
import { Button } from "@/components/base/buttons/button";

const selectCls =
  "appearance-none rounded-lg bg-primary px-3 py-2 text-sm text-primary shadow-xs ring-1 ring-primary outline-hidden ring-inset focus-visible:ring-2 focus-visible:ring-brand";

export function MeshAuditPager({ page, pages }: { page: number; pages: number }) {
  const router = useRouter();
  return (
    <nav className="flex flex-wrap items-center gap-2" aria-label="Страницы">
      <Button size="sm" color="secondary" href={`?page=${page - 1}`} isDisabled={page <= 1}>
        ← назад
      </Button>
      <label className="flex items-center gap-2 text-sm text-tertiary">
        стр.
        <select className={selectCls} value={page} onChange={(e) => router.push(`?page=${e.target.value}`)} aria-label="Номер страницы">
          {Array.from({ length: pages }, (_, i) => i + 1).map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        из {pages}
      </label>
      <Button size="sm" color="secondary" href={`?page=${page + 1}`} isDisabled={page >= pages}>
        вперёд →
      </Button>
    </nav>
  );
}
