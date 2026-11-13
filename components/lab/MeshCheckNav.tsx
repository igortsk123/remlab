// Шапка /lab/mesh-check (макет `.t118-mockup`): общий итог и полоса, разделы по типу товара с «проверено N из M» (липкие,
// под сквозной шапкой сайта, на телефоне листаются вбок), фильтр раздела «все / непроверенные / брак». Переходы — ссылками (?s=&f=&p=), без своего состояния.

import Link from "next/link";
import type { CheckFilter } from "@/lib/mesh-audit/repo-check";
import type { SectionCount } from "@/lib/mesh-audit/sections";

export function checkHref(s: string, f: CheckFilter, p = 1): string {
  return `?s=${s}${f === "all" ? "" : `&f=${f}`}${p > 1 ? `&p=${p}` : ""}`;
}

const FILTERS: readonly [CheckFilter, string][] = [
  ["all", "все"],
  ["todo", "непроверенные"],
  ["bad", "брак"],
];

export function MeshCheckTop({ counts }: { counts: readonly SectionCount[] }) {
  const total = counts.reduce((a, c) => a + c.total, 0);
  const checked = counts.reduce((a, c) => a + c.checked, 0);
  const pct = total ? Math.round((checked / total) * 100) : 0;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold text-primary">Проверка мешей</h1>
        <span className="text-sm text-tertiary">
          проверено {checked} из {total} · {pct} %
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-tertiary" aria-hidden="true">
        <div className="h-full rounded-full bg-success-solid" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function MeshCheckTabs({ counts, section }: { counts: readonly SectionCount[]; section: string }) {
  return (
    <nav aria-label="Разделы" style={{ top: "var(--site-header-h, 56px)" }} className="sticky z-10 -mx-4 flex gap-1.5 overflow-x-auto bg-secondary px-4 py-2 lg:flex-wrap lg:overflow-visible">
      {counts.map((c) => {
        const on = c.key === section;
        const done = c.checked === c.total;
        return (
          <Link
            key={c.key}
            href={checkHref(c.key, "all")}
            aria-current={on ? "page" : undefined}
            className={`flex min-h-11 flex-none items-center gap-1.5 rounded-full px-3 text-sm ring-1 ring-inset ${
              on ? "bg-primary-solid text-white ring-transparent" : "bg-primary text-secondary ring-secondary"
            }`}
          >
            <b className="font-semibold">{c.title}</b>
            <small className={`text-xs ${on ? "text-white" : done ? "text-success-primary" : "text-tertiary"}`}>
              {c.checked}/{c.total}
            </small>
          </Link>
        );
      })}
    </nav>
  );
}

export function MeshCheckFilter({ count, section, filter }: { count: SectionCount | undefined; section: string; filter: CheckFilter }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-base font-semibold text-primary">
        {count?.title ?? "Раздел"}{" "}
        <span className="text-sm font-normal text-tertiary">
          · проверено {count?.checked ?? 0} из {count?.total ?? 0}
        </span>
      </h2>
      <div className="flex overflow-hidden rounded-lg bg-primary ring-1 ring-secondary ring-inset" role="group" aria-label="Фильтр">
        {FILTERS.map(([f, label]) => (
          <Link
            key={f}
            href={checkHref(section, f)}
            aria-current={f === filter ? "true" : undefined}
            className={`flex min-h-11 items-center px-3 text-sm ${f === filter ? "bg-secondary font-semibold text-primary" : "text-secondary"}`}
          >
            {label}
          </Link>
        ))}
      </div>
    </div>
  );
}
