// Шапка /lab/cutout-check: общий итог и полоса, разделы по роли товара с «проверено N из M», фильтр «все / непроверенные / не ок».
// Переходы — ссылками (?r=&f=&p=), без своего состояния; подписи парой RU/EN.

import Link from "next/link";
import { L, type CheckFilter, type Counts, type Pair } from "@/lib/cutout-check/rules";
import type { RoleCount } from "@/lib/cutout-check/types";

export function checkHref(role: string | null, f: CheckFilter, p = 1): string {
  const q = [role ? `r=${encodeURIComponent(role)}` : "", f === "all" ? "" : `f=${f}`, p > 1 ? `p=${p}` : ""].filter(Boolean).join("&");
  return q ? `?${q}` : "?";
}

export function CutoutCheckTop({ all, run }: { all: Counts; run: string }) {
  const pct = all.total ? Math.round((all.checked / all.total) * 100) : 0;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="flex flex-col leading-tight">
          <span className="text-lg font-semibold text-primary">{L.title.ru}</span>
          <span className="text-xs font-normal text-tertiary">{L.title.en}</span>
        </h1>
        <span className="text-sm text-tertiary">
          {L.checked.ru} {all.checked} {L.of.ru} {all.total} · {pct} % · {L.badFilter.ru}: {all.bad}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-tertiary" aria-hidden="true">
        <div className="h-full rounded-full bg-success-solid" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-tertiary">
        {L.checked.en} {all.checked} {L.of.en} {all.total} · run {run} · {L.rule.ru} / {L.rule.en}
      </span>
    </div>
  );
}

export function CutoutCheckTabs({ roles, role, filter }: { roles: readonly RoleCount[]; role: string | null; filter: CheckFilter }) {
  const pill = (on: boolean) =>
    `flex min-h-11 flex-none items-center gap-1.5 rounded-full px-3 text-sm ring-1 ring-inset ${on ? "bg-primary-solid text-white ring-transparent" : "bg-primary text-secondary ring-secondary"}`;
  return (
    <nav aria-label="Разделы / Sections" style={{ top: "var(--site-header-h, 56px)" }} className="sticky z-10 -mx-4 flex gap-1.5 overflow-x-auto bg-secondary px-4 py-2 lg:flex-wrap lg:overflow-visible">
      <Link href={checkHref(null, filter)} aria-current={role === null ? "page" : undefined} className={pill(role === null)}>
        <b className="font-semibold">{L.all.ru} / {L.all.en}</b>
      </Link>
      {roles.map((c) => (
        <Link key={c.role} href={checkHref(c.role, filter)} aria-current={role === c.role ? "page" : undefined} className={pill(role === c.role)}>
          <b className="font-semibold">{c.role}</b>
          <small className="text-xs opacity-80">
            {c.checked}/{c.total}
          </small>
        </Link>
      ))}
    </nav>
  );
}

const FILTER_LABEL: Record<CheckFilter, Pair> = { all: L.all, todo: L.todo, bad: L.badFilter };

export function CutoutCheckFilter({ role, filter }: { role: string | null; filter: CheckFilter }) {
  return (
    <div className="flex overflow-hidden self-start rounded-lg bg-primary ring-1 ring-secondary ring-inset" role="group" aria-label="Фильтр / Filter">
      {(Object.keys(FILTER_LABEL) as CheckFilter[]).map((f) => (
        <Link key={f} href={checkHref(role, f)} aria-current={f === filter ? "true" : undefined} className={`flex min-h-11 flex-col items-center justify-center px-3 text-sm leading-tight ${f === filter ? "bg-secondary font-semibold text-primary" : "text-secondary"}`}>
          <span>{FILTER_LABEL[f].ru}</span>
          <span className="text-[11px] font-normal opacity-80">{FILTER_LABEL[f].en}</span>
        </Link>
      ))}
    </div>
  );
}
